"""Fixed and animated bake jobs and asynchronous timeline playback on Blender's main thread."""
from dataclasses import asdict
from pathlib import Path
import shutil
import time
import bpy
from bpy.app.handlers import persistent
from ..physics.cache import CacheWriter, CacheReader, fingerprint, estimate_bytes, validate_range
from ..physics.emission import Source
from ..physics.frame_cache import FrameCache
from ..backend.cache import capture, CachedFields
from ..backend.projected import DenseProjectedSmoke
from ..backend.timestep import AdaptiveTimestep
from ..backend.completion import StepCompletion
from .emitter import prepare_emission, prepare_additional_sources, emission_snapshot
from .collider import collider_snapshot, collider_bindings
from .animation import animation_signature
from ..physics.collider_motion import MotionPath
from ..physics.interaction import reset_signature
from ..physics.playback import source_span
from .domain import domain_object
from . import invalidation


class State:
    job = None
    reader = None
    fields = None
    scene = None
    handler = None
    previews = None
    frame = None
    message = ''
    progress = 0.0
    load_ms = 0.0
    signature = None
    memory = None
    direction = 1
    last_token = None
    memory_hit = False
    prefetch_ms = 0.0
    prefetch_failed = set()
    validity = invalidation.Memo()

STATE = State()


def snapshot(scene, animated=False):
    from .runtime import settings_from_scene
    grid, settings = settings_from_scene(scene)
    motion, _ = prepare_emission(scene, None)
    additional, _ = prepare_additional_sources(scene, None)
    sources = [Source(settings.source_center, settings.source_radius, settings.source_rate,
                      settings.heat_source_rate, motion, settings.density_mode, settings.source_profile,
                      settings.fuel_source_rate)] + additional
    colliders = collider_snapshot(scene)
    domain = domain_object(scene)
    matrix = [list(row) for row in domain.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world] if domain else None
    props = scene.fluxfx
    payload = dict(engine='fluxfx-0.25', grid=asdict(grid), settings=asdict(settings),
                   sources=[asdict(s) for s in sources], colliders=[asdict(c) for c in colliders],
                   domain=matrix, fps=scene.render.fps/scene.render.fps_base,
                   adaptive=props.adaptive_dt, dt=props.time_step, cfl=props.cfl_target,
                   empty=props.cache_start_empty)
    if animated:
        payload['motion_controls'] = [dict((name,getattr(entry,name)) for name in
            ('motion_inheritance','motion_speed_limit','continuous_trails','velocity_coupling','emission_enabled'))
            for entry in (props,*props.extra_emitters)]
    return grid, settings, sources, colliders, fingerprint(payload)


def storage_estimate(scene):
    p=scene.fluxfx
    channels=['DENSITY','TEMPERATURE']
    if p.combustion_enabled: channels+=['FUEL','FLAME']
    if any(c.enabled for c in p.colliders): channels+=['COLLISION']
    return estimate_bytes((int(p.resolution),)*3, channels, p.cache_start, p.cache_end)


class BakeJob:
    def __init__(self, scene):
        self.scene=scene; self.solver=self.ctl=self.fence=self.writer=None
        self.original_frame=(scene.frame_current,scene.frame_subframe)
        self.animated=scene.fluxfx.cache_animated
        self.prepared_frame=None; self.motion_path=None
        p=scene.fluxfx
        self.start,self.end=p.cache_start,p.cache_end
        self.fps=scene.render.fps/scene.render.fps_base
        validate_range(self.start,self.end,self.fps)
        self.adaptive,self.dt,self.cfl=p.adaptive_dt,p.time_step,p.cfl_target
        if p.cache_directory.startswith('//') and not bpy.data.filepath:
            raise ValueError('Save the blend file or choose an absolute bake folder')
        parent=Path(bpy.path.abspath(p.cache_directory)).expanduser()
        if not p.cache_directory: raise ValueError('Choose a bake folder')
        parent.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(parent).free < storage_estimate(scene): raise ValueError('Insufficient disk space for estimated bake')
        # Validate direct animation before changing the user's timeline.
        self.animation_signature=animation_signature(scene) if self.animated else None
        if self.animated: scene.frame_set(self.start)
        try:
            grid,settings,self.sources,colliders,self.signature=snapshot(scene,self.animated)
        except Exception:
            self.restore_frame(); raise
        self.initial_grid=grid; self.initial_settings=settings
        # Re-fingerprint only after an input may have changed (see invalidation.py).
        invalidation.watch(invalidation.watched_ids(scene))
        self.verified=invalidation.stamp(scene)
        self.bindings=collider_bindings(scene)
        self.frame_signature=self.signature
        self.history=emission_snapshot(scene)
        _,self.additional_history=prepare_additional_sources(scene,None)
        if settings.moving_colliders and not self.animated:
            self.restore_frame()
            raise ValueError('Enable Animated inputs to bake moving colliders')
        try:
            if shutil.disk_usage(parent).free < storage_estimate(scene):
                raise ValueError('Insufficient disk space at the first baked frame')
            self.solver=DenseProjectedSmoke(grid,settings,colliders=colliders)
            self.solver.reset(seed=not p.cache_start_empty)
            self.ctl=AdaptiveTimestep(grid,self.solver.device)
            self.fence=StepCompletion(self.solver.device)
            channels=['DENSITY','TEMPERATURE']
            if self.solver.combustion: channels+=['FUEL','FLAME']
            if self.solver.solids: channels+=['COLLISION']
            self.writer=CacheWriter(parent,grid,channels,self.start,self.end,self.fps,self.animation_signature if self.animated else self.signature,
                dict(blender=bpy.app.version_string,build=bpy.app.build_hash.decode(),input_frame=scene.frame_current,
                     mode='ANIMATED_INPUTS' if self.animated else 'FIXED_INPUTS',inputs={},initial_state='EMPTY' if p.cache_start_empty else 'SEEDED'),
                encoding='AUTO_ZLIB' if p.cache_compress else 'RAW')
            p.cache_path=str(self.writer.path)
            self.frame=self.start; self.started=time.perf_counter()
        except Exception:
            self.close(); raise

    def restore_frame(self):
        if self.animated:
            frame,subframe=self.original_frame
            self.scene.frame_set(frame,subframe=subframe)

    def unchanged(self):
        """True when no input could have changed since the last full check."""
        return invalidation.stamp(self.scene) == self.verified

    def verify(self):
        invalidation.watch(invalidation.watched_ids(self.scene))
        self.verified=invalidation.stamp(self.scene)

    def prepare_frame(self):
        if not self.unchanged():
            if animation_signature(self.scene) != self.animation_signature:
                raise ValueError('Animation changed during bake; start a new bake')
            if snapshot(self.scene,True)[-1] != self.frame_signature:
                raise ValueError('Simulation inputs changed during bake; start a new bake')
            self.verify()
        if self.prepared_frame == self.frame: return
        self.scene.frame_set(self.frame)
        grid,settings,_,colliders,self.frame_signature=snapshot(self.scene,True)
        if grid != self.initial_grid or reset_signature(settings) != reset_signature(self.initial_settings):
            raise ValueError('Grid and initial/solver mode settings must stay constant during animated bake')
        p=self.scene.fluxfx
        if (p.adaptive_dt,p.time_step,p.cfl_target) != (self.adaptive,self.dt,self.cfl):
            raise ValueError('Timestep controls must stay constant during animated bake')
        if self.scene.render.fps/self.scene.render.fps_base != self.fps:
            raise ValueError('FPS must stay constant during animated bake')
        if collider_bindings(self.scene) != self.bindings:
            raise ValueError('Collider membership must stay constant during animated bake')
        self.solver.update_settings(settings)
        motion,self.history=prepare_emission(self.scene,self.history,interval=1/self.fps)
        additional,self.additional_history=prepare_additional_sources(self.scene,self.additional_history,interval=1/self.fps)
        self.sources=[Source(settings.source_center,settings.source_radius,settings.source_rate,
            settings.heat_source_rate,motion,settings.density_mode,settings.source_profile,settings.fuel_source_rate)]+additional
        if settings.moving_colliders and self.solver.solids:
            self.motion_path=MotionPath(self.solver.solids.colliders,colliders,1/self.fps)
            if self.motion_path.duration > 1/self.fps+1e-6:
                raise ValueError('Animated collider exceeds 2 m/s surface speed; slow its animation')
        elif colliders != (self.solver.solids.colliders if self.solver.solids else ()):
            raise ValueError('Static collider changed; enable moving mode for sphere/box motion')
        self.prepared_frame=self.frame
        self.verify()  # frame_set does not count as an edit; this frame's inputs are now the baseline

    def advance(self, budget=.02):
        if self.animated: self.prepare_frame()
        elif not self.unchanged():
            if snapshot(self.scene)[-1] != self.signature:
                raise ValueError('Simulation inputs changed during bake; start a new bake')
            self.verify()
        end_time=(self.frame-self.start)/self.fps
        deadline=time.perf_counter()+budget
        while end_time-self.solver.time > 1e-8:
            maximum=min(self.dt,end_time-self.solver.time)
            dt=self.ctl.select(self.solver,maximum,self.cfl,sources=self.sources)['dt'] if self.adaptive else maximum
            sources=self.sources
            if self.animated:
                elapsed=max(0.,self.solver.time-(self.frame-self.start-1)/self.fps)
                if self.motion_path:
                    dt=self.motion_path.limit_dt(dt,self.solver.grid.cell_size)
                    self.solver.move_colliders(self.motion_path.at(elapsed+dt),dt)
                sources=[source_span(source,min(1.,elapsed*self.fps),min(1.,(elapsed+dt)*self.fps)) for source in self.sources]
            self.solver.step(dt,sources=sources); self.fence.wait(self.solver)
            if time.perf_counter()>=deadline: return False
        if self.animated:
            self.writer.meta['provenance']['inputs'][str(self.frame)]=self.frame_signature
        self.writer.write(self.frame,capture(self.solver))
        STATE.progress=(self.frame-self.start+1)/(self.end-self.start+1)
        STATE.message=f'Baked {self.frame-self.start+1}/{self.end-self.start+1} frames'
        self.frame+=1
        if self.frame>self.end:
            self.writer.finish()
            stored=sum(record['bytes'] for record in self.writer.meta['frames'].values())
            STATE.message=f'Bake complete · {self.end-self.start+1} frames · {stored/2**20:.1f} MiB · {time.perf_counter()-self.started:.1f}s'
            return True
        return False

    def close(self):
        for v in (self.fence,self.ctl,self.solver):
            if v is not None: v.close()
        self.fence=self.ctl=self.solver=None
        self.restore_frame()


def cache_matches(scene,reader):
    provenance=reader.meta.get('provenance',{})
    if provenance.get('mode')=='ANIMATED_INPUTS':
        if animation_signature(scene) != reader.meta['signature']: return False
        expected=provenance.get('inputs',{}).get(str(scene.frame_current))
        return expected is None or snapshot(scene,True)[-1]==expected
    return snapshot(scene)[-1]==reader.meta['signature']


def playback_valid(scene, reader):
    """cache_matches, memoised per frame until an input may have changed.

    An idle timeline costs one cheap stamp per tick; each newly displayed frame
    is fingerprinted once; revisiting a verified frame costs nothing.
    """
    stamp = invalidation.stamp(scene)
    memo = STATE.validity
    if stamp != memo.stamp:
        invalidation.watch(invalidation.watched_ids(scene))
    provenance=reader.meta.get('provenance',{})
    if provenance.get('mode')=='ANIMATED_INPUTS':
        if not memo.get(stamp, 'animation', lambda: animation_signature(scene) == reader.meta['signature']):
            return False
        frame=scene.frame_current
        expected=provenance.get('inputs',{}).get(str(frame))
        return expected is None or memo.get(stamp, frame, lambda: snapshot(scene,True)[-1]==expected)
    return memo.get(stamp, scene.frame_current, lambda: snapshot(scene)[-1]==reader.meta['signature'])


def stop_bake(status='CANCELLED', message='Bake cancelled; completed frames kept'):
    job=STATE.job; STATE.job=None
    if bpy.app.timers.is_registered(bake_tick): bpy.app.timers.unregister(bake_tick)
    if job:
        try: job.writer.finish(status,message)
        except Exception as exc: message += f'; could not update manifest: {exc}'
        finally: job.close()
        STATE.message=message


def bake_tick():
    job=STATE.job
    if job is None: return None
    try:
        if bpy.context.scene != job.scene:
            stop_bake(message='Bake cancelled after scene change'); return None
        if job.advance():
            job.close(); STATE.job=None
            from .runtime import redraw
            redraw(); return None
    except Exception as exc:
        try: stop_bake('FAILED',str(exc))
        except Exception: job.close(); STATE.job=None; STATE.message=str(exc)
        return None
    from .runtime import redraw
    redraw()
    return .01


def start_bake(scene):
    from . import runtime
    runtime.shutdown()
    STATE.progress=0
    STATE.job=BakeJob(scene)
    STATE.message='Baking animated inputs' if scene.fluxfx.cache_animated else 'Baking fixed inputs from the current scene'
    bpy.app.timers.register(bake_tick,first_interval=.01)


def release_playback():
    if STATE.reader is not None: STATE.message='Cache playback released'
    if bpy.app.timers.is_registered(playback_tick): bpy.app.timers.unregister(playback_tick)
    if STATE.handler is not None: bpy.types.SpaceView3D.draw_handler_remove(STATE.handler,'WINDOW')
    if bpy.app.timers.is_registered(prefetch_tick): bpy.app.timers.unregister(prefetch_tick)
    if STATE.memory: STATE.memory.clear()
    STATE.memory=None; STATE.last_token=None; STATE.prefetch_failed=set()
    STATE.direction=1; STATE.memory_hit=False; STATE.prefetch_ms=0.0
    if STATE.fields: STATE.fields.close()
    STATE.reader=STATE.fields=STATE.scene=STATE.handler=STATE.previews=STATE.frame=None
    STATE.signature=None
    STATE.validity.reset()


def shutdown():
    stop_bake()
    release_playback()


def load_cache(scene):
    from . import runtime
    from .preview import SlicePreview
    from .scene_preview import ScenePreview
    runtime.shutdown()
    reader=CacheReader(bpy.path.abspath(scene.fluxfx.cache_path))
    if not cache_matches(scene,reader):
        raise ValueError('Cache is outdated: simulation inputs or FPS differ; bake again')
    if not reader.meta['frames']: raise ValueError('Cache has no completed frames')
    try:
        STATE.reader=reader; STATE.scene=scene; STATE.fields=CachedFields(reader.grid)
        STATE.memory=FrameCache(reader,scene.fluxfx.cache_memory_mb*2**20)
        STATE.previews=(SlicePreview(),SlicePreview(volume=True),ScenePreview())
        STATE.handler=bpy.types.SpaceView3D.draw_handler_add(draw,(),'WINDOW','POST_PIXEL')
        STATE.frame=None; STATE.message='Cache loaded · scrub the Blender timeline'
        try: update_playback()
        except (ValueError, OSError) as exc: STATE.message=str(exc)
        bpy.app.timers.register(playback_tick,first_interval=.03)
    except Exception:
        release_playback(); raise


def update_playback():
    """Show the scene's current frame; returns True when the display changed."""
    scene=STATE.scene
    if not playback_valid(scene,STATE.reader):
        STATE.fields.close(); STATE.frame=None; STATE.memory.clear()
        raise ValueError('Cache outdated: simulation inputs changed; bake again')
    frame=scene.frame_current
    STATE.memory.configure(scene.fluxfx.cache_memory_mb*2**20)
    # Even the currently displayed frame must stop showing if its file changes.
    try: token=STATE.memory.token(frame)
    except (ValueError,OSError):
        STATE.fields.close(); STATE.frame=None
        raise
    if frame==STATE.frame and token==STATE.last_token: return False
    if STATE.frame is not None and frame != STATE.frame:
        STATE.direction=1 if frame>STATE.frame else -1
        STATE.prefetch_failed.clear()
    start=time.perf_counter()
    # Clear old contents on failure so missing/corrupt frames never show stale smoke.
    STATE.fields.close(); STATE.frame=None
    fields,STATE.memory_hit=STATE.memory.get(frame)
    STATE.fields.upload(fields,scene.fluxfx.preview_channel); STATE.frame=frame
    # Keep the pre-read token so a file changed during upload is caught next tick.
    STATE.last_token=token
    STATE.load_ms=(time.perf_counter()-start)*1000
    STATE.message=f'Cached frame {frame} · {"RAM hit" if STATE.memory_hit else "disk read"} · {STATE.reader.meta["status"].lower()}'
    return True


def playback_tick():
    if STATE.reader is None: return None
    if STATE.scene != bpy.context.scene:
        release_playback(); STATE.message='Cache playback released after scene change'; return None
    started=time.perf_counter()
    try: changed=update_playback()
    except Exception as exc:
        changed=STATE.frame is not None or STATE.message!=str(exc)
        STATE.fields.close(); STATE.frame=None; STATE.message=str(exc)
    schedule_prefetch()
    if changed:  # an idle timeline must not re-raymarch the viewport every tick
        from .runtime import redraw
        redraw()
    # Frame changes reschedule this timer immediately (frame_changed); between
    # them it only polls for edits and file changes, so it can idle slowly.
    return max(.001,.1-(time.perf_counter()-started))


def schedule_prefetch():
    if (STATE.reader is not None and STATE.frame is not None and
            STATE.scene.fluxfx.cache_prefetch and STATE.memory.capacity > 1 and
            not bpy.app.timers.is_registered(prefetch_tick)):
        bpy.app.timers.register(prefetch_tick,first_interval=.001)


def prefetch_tick():
    # One CPU read per callback. No bpy or GPU work in a background thread.
    # A frame-change callback takes priority by cancelling this pending timer.
    if (STATE.reader is None or STATE.scene != bpy.context.scene or STATE.frame is None or
            STATE.scene.frame_current != STATE.frame or not STATE.scene.fluxfx.cache_prefetch):
        return None
    STATE.memory.configure(STATE.scene.fluxfx.cache_memory_mb*2**20)
    for frame in STATE.memory.upcoming(STATE.frame,STATE.direction):
        if frame in STATE.prefetch_failed: continue
        try:
            if STATE.memory.current(frame): continue
            start=time.perf_counter(); STATE.memory.get(frame)
            STATE.prefetch_ms=(time.perf_counter()-start)*1000
        except (ValueError,OSError):
            # A bad future frame must not hide the valid currently displayed one.
            STATE.prefetch_failed.add(frame)
        return .001
    return None


def draw():
    if STATE.scene != bpy.context.scene or STATE.fields is None or STATE.frame is None or STATE.frame != STATE.scene.frame_current: return
    props=STATE.scene.fluxfx
    if not props.show_preview or props.preview_channel not in STATE.fields.fields: return
    try:
        if props.preview_mode=='SCENE': STATE.previews[2].draw(STATE.fields,STATE.scene)
        else:
            STATE.previews[props.preview_mode=='VOLUME'].draw(STATE.fields,props.slice_y,props.exposure,
                props.preview_channel,int(props.ray_steps))
    except Exception as exc:
        STATE.message=f'Cache preview: {exc}'; STATE.fields.close(); STATE.frame=None


@persistent
def frame_changed(scene, *_):
    # Frame handlers may run outside a drawing context. Schedule GPU work for the
    # main-thread timer instead of uploading here; coalesce rapid scrub events.
    if STATE.reader is not None and STATE.scene == scene:
        if bpy.app.timers.is_registered(prefetch_tick): bpy.app.timers.unregister(prefetch_tick)
        if bpy.app.timers.is_registered(playback_tick): bpy.app.timers.unregister(playback_tick)
        bpy.app.timers.register(playback_tick, first_interval=0.0)
