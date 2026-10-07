"""Actual Blender timer/operator bake, cancel, scrub and disable validation."""
from pathlib import Path
import bpy,json,tempfile,time,traceback
import fluxfx
from fluxfx.blender import cache,runtime
from fluxfx.blender.domain import create_domain
from fluxfx.physics.cache import CacheReader
ROOT=Path(__file__).resolve().parents[1]


def run():
    old=bpy.context.window.scene
    scene=bpy.data.scenes.new('FluxFX Cache UI Test');bpy.context.window.scene=scene
    temp=tempfile.TemporaryDirectory(prefix='fluxfx-cache-ui-')
    p=scene.fluxfx;p.resolution='32';p.cache_directory=temp.name;p.cache_start=1;p.cache_end=24
    p.initial_temperature=0;p.turbulence_strength=1
    create_domain(scene)
    report={'status':'RUNNING','tests':[]};stage=0;first=None;deadline=time.perf_counter()+60
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    def cleanup():
        runtime.shutdown();objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
        temp.cleanup()
        (ROOT/'test-results/cache-ui-validation.json').write_text(json.dumps(report,indent=2))
        print('FLUXFX_CACHE_UI',report['status'],report.get('traceback',''))
    def poll():
        nonlocal stage,first
        try:
            if time.perf_counter()>deadline:raise TimeoutError('Cache UI test timeout')
            if stage==0:
                if cache.STATE.job:return .05
                check('timer_bake_complete',CacheReader(p.cache_path).meta['status']=='COMPLETE')
                check('completed_timer_removed',not bpy.app.timers.is_registered(cache.bake_tick))
                first=p.cache_path;scene.frame_set(24)
                check('load_operator',bpy.ops.fluxfx.cache(action='LOAD')=={'FINISHED'})
                stage=1;return .1
            if stage==1:
                check('timer_loads_last_frame',cache.STATE.frame==24 and bool(cache.STATE.fields.fields))
                scene.frame_set(12);stage=2;return .1
            if stage==2:
                check('timer_scrubs_backwards',cache.STATE.frame==12)
                p.cache_end=240
                check('bake_operator',bpy.ops.fluxfx.cache(action='BAKE')=={'FINISHED'})
                stage=3;return .1
            if stage==3:
                check('cancel_operator',bpy.ops.fluxfx.cache(action='CANCEL')=={'FINISHED'})
                reader=CacheReader(p.cache_path)
                check('cancel_keeps_partial_frames',reader.meta['status']=='CANCELLED' and 0<len(reader.meta['frames'])<240)
                check('cancel_timer_removed',not bpy.app.timers.is_registered(cache.bake_tick))
                p.cache_path=first;scene.frame_set(24);cache.load_cache(scene)
                fluxfx.unregister()
                check('disable_releases_playback',cache.STATE.reader is None and cache.STATE.handler is None and not bpy.app.timers.is_registered(cache.playback_tick))
                fluxfx.register()
                report['status']='PASS';cleanup();return None
        except Exception:
            report['status']='FAIL';report['traceback']=traceback.format_exc();cleanup();return None
    try:
        check('start_operator',bpy.ops.fluxfx.cache(action='BAKE')=={'FINISHED'})
        bpy.app.timers.register(poll,first_interval=.1)
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc();cleanup()
if __name__=='__main__':run()
