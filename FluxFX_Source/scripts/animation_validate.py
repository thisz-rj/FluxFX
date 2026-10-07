"""Animated bake oracles in graphical Blender; temporary scene and files."""
from pathlib import Path
import tempfile,json,traceback
import bpy
from fluxfx.blender import cache,runtime
from fluxfx.blender.animation import animation_signature
from fluxfx.blender.emitter import create_emitter,create_additional_emitter
from fluxfx.blender.collider import create_collider,collider_snapshot
from fluxfx.physics.cache import CacheReader
ROOT=Path(__file__).resolve().parents[1]


def curves(owner):
    return [fc for layer in owner.animation_data.action.layers for strip in layer.strips
            for bag in strip.channelbags if bag.slot_handle==owner.animation_data.action_slot_handle for fc in bag.fcurves]


def linear(owner):
    for fc in curves(owner):
        for k in fc.keyframe_points:k.interpolation='LINEAR'


def run_suite(compressed=False):
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Animated Bake Test');bpy.context.window.scene=scene
    report={'status':'RUNNING','tests':[]};job=None
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    try:
        with tempfile.TemporaryDirectory(prefix='fluxfx-animation-') as folder:
            p=scene.fluxfx;p.resolution='16';p.show_preview=False;p.cache_directory=folder
            p.cache_animated=True;p.cache_compress=compressed;p.cache_start=1;p.cache_end=9;p.initial_temperature=0
            p.moving_colliders=True;p.combustion_enabled=True;p.turbulence_strength=1
            emitter=create_emitter(scene);extra=create_additional_emitter(scene)
            box=create_collider(scene,'BOX');box.location=(.12,0,.25);box.scale=(.1,.12,.1)
            for f,x,r,heat,rate in [(1,-.15,.10,200,1),(9,.15,.16,800,3)]:
                emitter.location.x=x;emitter.scale=(r,)*3
                emitter.keyframe_insert(data_path='location',frame=f);emitter.keyframe_insert(data_path='scale',frame=f)
                p.heat_source_rate=heat;p.source_rate=rate
                scene.keyframe_insert(data_path='fluxfx.heat_source_rate',frame=f);scene.keyframe_insert(data_path='fluxfx.source_rate',frame=f)
                box.location.x=.12+x*.2;box.rotation_euler.z=x
                box.keyframe_insert(data_path='location',frame=f);box.keyframe_insert(data_path='rotation_euler',frame=f)
                extra.location.x=-x;extra.keyframe_insert(data_path='location',frame=f)
            for owner in (scene,emitter,extra,box):linear(owner)
            scene.frame_set(5);signature=animation_signature(scene);scene.frame_set(9)
            check('animation_hash_independent_of_current_frame',animation_signature(scene)==signature)
            scene.frame_set(20,subframe=.25)
            def bake(budget=.0001):
                nonlocal job
                job=cache.BakeJob(scene);samples=[]
                while True:
                    complete=job.advance(budget=budget)
                    if job.prepared_frame and (not samples or samples[-1][0]!=job.prepared_frame):
                        samples.append((job.prepared_frame,job.solver.settings.source_radius,job.solver.settings.source_rate,job.solver.settings.heat_source_rate))
                    if complete:break
                check('exact_end_time',abs(job.solver.time-8/(scene.render.fps/scene.render.fps_base))<1e-7)
                check('wall_tracks_final_pose',max(abs(a-b) for x,y in zip(job.solver.solids.colliders,collider_snapshot(scene)) for r,s in zip(x.inverse_rows,y.inverse_rows) for a,b in zip(r,s))<1e-5)
                reader=CacheReader(p.cache_path);job.close();job=None
                return reader,samples
            first,samples=bake()
            check('restores_original_frame_and_subframe',scene.frame_current==20 and abs(scene.frame_subframe-.25)<1e-7)
            check('animated_size_rate_and_heat_sampled',samples[0][1]<samples[-1][1] and samples[0][2]<samples[-1][2] and samples[0][3]<samples[-1][3])
            check('all_frame_input_signatures_saved',len(first.meta['provenance']['inputs'])==9)
            check('collision_mask_animates',list(first.read(1)['COLLISION'])!=list(first.read(9)['COLLISION']))
            check('nonempty_density_and_heat',max(first.read(9)['DENSITY'])>0 and max(first.read(9)['TEMPERATURE'])>0)
            second,_=bake(.05)
            check('repeat_bake_bit_exact',all(first.meta['frames'][str(f)]['crc32']==second.meta['frames'][str(f)]['crc32'] for f in range(1,10)))
            scene.frame_set(4);p.cache_path=str(first.path);cache.load_cache(scene)
            check('animated_cache_loads_at_middle',cache.STATE.frame==4)
            scene.frame_set(8);cache.update_playback();check('animated_scrub_not_stale',cache.STATE.frame==8)
            # Edit an earlier key while a later endpoint remains numerically identical.
            curve=next(fc for fc in curves(emitter) if fc.data_path=='location' and fc.array_index==0)
            previous=curve.keyframe_points[0].co.y;curve.keyframe_points[0].co.y+=.02;curve.update()
            scene.frame_set(9);cache.playback_tick()
            check('earlier_key_edit_invalidates_later_frame',cache.STATE.frame is None and 'outdated' in cache.STATE.message)
            curve.keyframe_points[0].co.y=previous;curve.update();scene.frame_set(4);cache.playback_tick()
            check('restoring_animation_recovers',cache.STATE.frame==4)
            p.motion_inheritance=.5;cache.playback_tick()
            check('motion_inheritance_edit_invalidates',cache.STATE.frame is None)
            p.motion_inheritance=0
            cache.release_playback()
            # Cancel after a completed prefix and restore the user's timeline.
            scene.frame_set(20,subframe=.5);cache.start_bake(scene);job=cache.STATE.job
            bpy.app.timers.unregister(cache.bake_tick);job.advance();path=p.cache_path;cache.stop_bake();job=None
            check('cancel_restores_timeline',scene.frame_current==20 and scene.frame_subframe==.5)
            check('cancel_keeps_animated_prefix',CacheReader(path).meta['status']=='CANCELLED' and len(CacheReader(path).meta['frames'])==1)
            # Too-fast collider motion must fail instead of a hidden tracking delay.
            fc=next(fc for fc in curves(box) if fc.data_path=='location' and fc.array_index==0)
            fc.keyframe_points[-1].co.y=3;fc.update();scene.frame_set(20)
            job=cache.BakeJob(scene)
            try:
                while not job.advance():pass
                rejected=False
            except ValueError as exc:rejected='speed' in str(exc)
            check('fast_wall_rejected',rejected);job.close();job=None
            check('failure_restores_timeline',scene.frame_current==20)
            report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        if job:job.close()
        runtime.shutdown();objects=list(scene.objects);actions=[o.animation_data.action for o in [scene,*objects] if o.animation_data and o.animation_data.action]
        bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
        for action in actions:
            if action.users==0:bpy.data.actions.remove(action)
        (ROOT/('test-results/compressed-animation-validation.json' if compressed else 'test-results/animation-validation.json')).write_text(json.dumps(report,indent=2))
    print('FLUXFX_ANIMATION',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
