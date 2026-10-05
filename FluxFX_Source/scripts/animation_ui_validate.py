"""Asynchronous animated bake, cancellation and timeline handler validation."""
from pathlib import Path
import bpy,json,tempfile,time,traceback
from fluxfx.blender import cache,runtime
from fluxfx.blender.emitter import create_emitter
from fluxfx.physics.cache import CacheReader
ROOT=Path(__file__).resolve().parents[1]


def run(on_complete=None, compressed=False):
    old=bpy.context.window.scene
    scene=bpy.data.scenes.new('FluxFX Animated Timer Test');bpy.context.window.scene=scene
    temp=tempfile.TemporaryDirectory(prefix='fluxfx-animated-ui-')
    p=scene.fluxfx;p.resolution='16';p.show_preview=False;p.cache_directory=temp.name
    p.cache_animated=True;p.cache_compress=compressed;p.cache_start=1;p.cache_end=8
    emitter=create_emitter(scene)
    for f,x in [(1,-.1),(8,.1)]:
        emitter.location.x=x;emitter.keyframe_insert(data_path='location',frame=f)
    scene.frame_set(20,subframe=.25)
    added=cache.frame_changed not in bpy.app.handlers.frame_change_post
    if added:bpy.app.handlers.frame_change_post.append(cache.frame_changed)
    report={'status':'RUNNING','tests':[]};stage=0;deadline=time.perf_counter()+60
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    def cleanup():
        runtime.shutdown()
        if added and cache.frame_changed in bpy.app.handlers.frame_change_post:bpy.app.handlers.frame_change_post.remove(cache.frame_changed)
        action=emitter.animation_data.action;objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
        if action.users==0:bpy.data.actions.remove(action)
        temp.cleanup()
        (ROOT/('test-results/compressed-animation-ui-validation.json' if compressed else 'test-results/animation-ui-validation.json')).write_text(json.dumps(report,indent=2))
        print('FLUXFX_ANIMATION_UI',report['status'],report.get('traceback',''))
        if on_complete:on_complete()
    def poll():
        nonlocal stage
        try:
            if time.perf_counter()>deadline:raise TimeoutError('Animated UI test timeout')
            if stage==0:
                if cache.STATE.job:return .02
                check('animated_timer_bake_complete',CacheReader(p.cache_path).meta['status']=='COMPLETE')
                check('timer_restores_frame',scene.frame_current==20 and scene.frame_subframe==.25)
                check('bake_timer_removed',not bpy.app.timers.is_registered(cache.bake_tick))
                scene.frame_set(3);cache.load_cache(scene);scene.frame_set(7)
                stage=1;return .1
            if stage==1:
                check('frame_handler_scrubs_animated_cache',cache.STATE.frame==7)
                check('prefetch_populates_future_frame',8 in cache.STATE.memory.entries)
                p.cache_end=240;scene.frame_set(20,subframe=.5);cache.start_bake(scene)
                stage=2;return .1
            if stage==2:
                cache.stop_bake()
                check('cancelled_animated_timer_cache',CacheReader(p.cache_path).meta['status']=='CANCELLED')
                check('cancel_restores_frame',scene.frame_current==20 and scene.frame_subframe==.5)
                check('cancel_releases_resources',cache.STATE.job is None and not bpy.app.timers.is_registered(cache.bake_tick))
                report['status']='PASS';cleanup();return None
        except Exception:
            report['status']='FAIL';report['traceback']=traceback.format_exc();cleanup();return None
    try:
        cache.start_bake(scene);bpy.app.timers.register(poll,first_interval=.1)
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc();cleanup()
if __name__=='__main__':run()
