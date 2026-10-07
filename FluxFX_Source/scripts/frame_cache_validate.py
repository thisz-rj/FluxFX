"""Graphical frame-pool correctness, prefetch and completed GPU timings."""
from pathlib import Path
from time import perf_counter
from statistics import median
import tempfile,json,traceback
import bpy
from fluxfx.blender import cache,runtime
from fluxfx.blender.collider import create_collider
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    report=dict(status='RUNNING',tests=[],timings=[],blender=bpy.app.version_string,build=bpy.app.build_hash.decode())
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Frame Pool Test');bpy.context.window.scene=scene
    p=scene.fluxfx;p.show_preview=False;p.cache_compress=True;p.cache_prefetch=False
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    try:
        with tempfile.TemporaryDirectory(prefix='fluxfx-frame-pool-') as folder:
            p.cache_directory=folder;p.cache_start=1;p.cache_end=4;p.cache_start_empty=False
            p.combustion_enabled=True;p.heat_source_rate=1000;create_collider(scene,'BOX');bpy.context.view_layer.update()
            for n in (64,128):
                p.resolution=str(n);cache.start_bake(scene);job=cache.STATE.job;bpy.app.timers.unregister(cache.bake_tick)
                while not job.advance():pass
                job.close();cache.STATE.job=None;scene.frame_set(1);p.cache_memory_mb=0;cache.load_cache(scene)
                timing={};baseline={}
                for mode in ('disk','memory'):
                    p.cache_memory_mb=0 if mode=='disk' else 256
                    if mode=='memory':
                        for f in range(1,5):scene.frame_set(f);cache.update_playback()
                    costs=[]
                    for _ in range(2):
                        for f in range(1,5):
                            scene.frame_set(f);start=perf_counter();cache.update_playback()
                            cache.STATE.fields.preview_field('DENSITY').read()
                            costs.append((perf_counter()-start)*1000)
                            if mode=='disk':baseline[f]=cache.STATE.fields.fields['DENSITY'].tobytes()
                            else:assert baseline[f]==cache.STATE.fields.fields['DENSITY'].tobytes()
                    timing[mode]=dict(median_ms=median(costs),max_ms=max(costs))
                check(f'{n}_cached_uploads_equal_disk',True)
                check(f'{n}_memory_hit',cache.STATE.memory_hit)
                check(f'{n}_pool_bounded',cache.STATE.memory.used_bytes<=256*2**20)
                report['timings'].append(dict(grid=n,frames=4,channels=5,**timing))
                cache.release_playback()
            scene.frame_set(1);p.cache_memory_mb=128;cache.load_cache(scene)
            p.cache_prefetch=True
            check('prefetch_one_frame_per_callback',cache.prefetch_tick()==.001 and 2 in cache.STATE.memory.entries and 3 not in cache.STATE.memory.entries)
            cache.prefetch_tick();check('prefetch_two_ahead',3 in cache.STATE.memory.entries)
            scene.frame_set(2);cache.update_playback();check('prefetched_frame_is_hit',cache.STATE.memory_hit)
            scene.frame_set(1);cache.update_playback();check('reverse_scrub_direction',cache.STATE.direction==-1)
            # Invalid future frame must not disturb the displayed frame.
            cache.STATE.memory.clear();cache.STATE.direction=1
            path=Path(p.cache_path)/'frame_2.fxc';saved=path.read_bytes();path.write_bytes(b'bad')
            cache.prefetch_tick();check('bad_future_keeps_current',cache.STATE.frame==1 and 2 in cache.STATE.prefetch_failed)
            scene.frame_set(2);cache.playback_tick();check('bad_requested_frame_clears_preview',cache.STATE.frame is None and not cache.STATE.fields.fields)
            path.write_bytes(saved);scene.frame_set(2);cache.update_playback();check('repaired_frame_recovers',cache.STATE.frame==2)
            # Current-frame corruption must be detected without scrubbing away first.
            path.write_bytes(b'bad');cache.playback_tick();check('current_frame_corruption_detected',cache.STATE.frame is None)
            path.write_bytes(saved);cache.update_playback()
            path.unlink()
            try: cache.update_playback()
            except OSError: pass
            check('deleted_current_frame_clears_on_direct_update',cache.STATE.frame is None and not cache.STATE.fields.fields)
            path.write_bytes(saved);cache.update_playback()
            original_upload=cache.STATE.fields.upload
            def changing_upload(fields,channel):
                original_upload(fields,channel);path.write_bytes(b'changed during upload')
            cache.STATE.fields.upload=changing_upload;cache.STATE.frame=None
            try:cache.update_playback()
            finally:cache.STATE.fields.upload=original_upload
            cache.playback_tick()
            check('file_changed_during_upload_detected_next_tick',cache.STATE.frame is None)
            path.write_bytes(saved);cache.update_playback()
            p.source_rate+=1;cache.playback_tick();check('stale_inputs_clear_pool',cache.STATE.memory.used_bytes==0 and cache.STATE.frame is None)
            p.source_rate-=1;cache.update_playback()
            p.cache_memory_mb=0;cache.update_playback();check('live_limit_zero_evicts',cache.STATE.memory.used_bytes==0)
            p.cache_memory_mb=128;cache.STATE.memory.configure(128*2**20);cache.schedule_prefetch()
            check('prefetch_timer_scheduled',bpy.app.timers.is_registered(cache.prefetch_tick))
            cache.frame_changed(scene)
            check('scrub_cancels_pending_prefetch',not bpy.app.timers.is_registered(cache.prefetch_tick))
            # Latest scene frame wins when several handler events precede a tick.
            for f in (1,4,2):scene.frame_set(f);cache.frame_changed(scene)
            cache.playback_tick();check('rapid_scrub_latest_wins',cache.STATE.frame==2)
            pool=cache.STATE.memory;cache.schedule_prefetch();bpy.context.window.scene=old;cache.playback_tick()
            check('scene_change_releases_pool_and_timers',cache.STATE.memory is None and pool.used_bytes==0 and not bpy.app.timers.is_registered(cache.prefetch_tick))
            bpy.context.window.scene=scene;cache.load_cache(scene);pool=cache.STATE.memory
            runtime.before_undo(None)
            check('undo_releases_pool',pool.used_bytes==0 and cache.STATE.memory is None)
            report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        runtime.shutdown();objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
        (ROOT/'test-results/frame-cache-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_FRAME_CACHE',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
