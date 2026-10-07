"""Graphical Blender cache correctness, cancellation, lifecycle and throughput."""
from pathlib import Path
from time import perf_counter
from statistics import median
import tempfile,json,traceback
import bpy
from fluxfx.blender import cache,runtime
from fluxfx.blender.emitter import create_additional_emitter
from fluxfx.backend.cache import capture
from fluxfx.physics.cache import CacheReader
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    report={'status':'RUNNING','tests':[],'timings':[]}
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Cache Test');bpy.context.window.scene=scene
    p=scene.fluxfx;p.resolution='16';p.source_mode='MANUAL';p.show_preview=False
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    try:
        with tempfile.TemporaryDirectory(prefix='fluxfx-cache-test-') as directory:
            p.cache_directory=directory;p.cache_start=3;p.cache_end=6
            p.combustion_enabled=True;p.heat_source_rate=1000;p.turbulence_strength=2
            bpy.ops.mesh.primitive_cube_add(size=.25,location=(.1,0,.6))
            bpy.ops.fluxfx.add_mesh_collider();create_additional_emitter(scene);bpy.context.view_layer.update()
            cache.start_bake(scene);job=cache.STATE.job
            check('bake_has_timer_and_no_live_solver',bpy.app.timers.is_registered(cache.bake_tick) and runtime.STATE.solver is None)
            bpy.app.timers.unregister(cache.bake_tick)
            while not job.advance():pass
            expected=capture(job.solver);path=p.cache_path;reader=CacheReader(path)
            check('complete_and_exact_frame_count',reader.meta['status']=='COMPLETE' and len(reader.meta['frames'])==4)
            check('frame_clock',abs(job.solver.time-3/(scene.render.fps/scene.render.fps_base))<1e-7)
            check('initial_frame_empty',all(v==0 for k,a in reader.read(3).items() if k!='COLLISION' for v in a))
            actual=reader.read(6)
            check('all_five_channels',set(actual)=={'DENSITY','TEMPERATURE','FUEL','FLAME','COLLISION'})
            check('bit_exact_disk_fields',all(list(actual[k])==v for k,v in expected.items()))
            job.close();cache.STATE.job=None
            scene.frame_set(6);cache.load_cache(scene)
            check('playback_no_solver_and_compiled_preview',runtime.STATE.solver is None and len(cache.STATE.previews)==3)
            check('gpu_roundtrip',all(cache.STATE.fields.device.read(cache.STATE.fields.preview_field(k),reader.grid.shape)==v for k,v in expected.items()))
            scene.frame_set(3);cache.update_playback()
            check('backward_scrub',cache.STATE.frame==3)
            scene.frame_set(7);cache.playback_tick()
            check('missing_frame_clears_display',cache.STATE.frame is None and not cache.STATE.fields.fields)
            scene.frame_set(5);cache.playback_tick()
            check('scrub_recovers_valid_frame',cache.STATE.frame==5)
            p.exposure=5;cache.update_playback()
            check('display_edit_keeps_cache',cache.STATE.frame==5)
            p.source_rate+=1;cache.playback_tick()
            check('settings_change_marks_stale',cache.STATE.frame is None and 'outdated' in cache.STATE.message)
            p.source_rate-=1;cache.playback_tick()
            check('reverted_settings_recover',cache.STATE.frame==5)
            scene.render.fps+=1;cache.playback_tick()
            check('fps_change_marks_stale',cache.STATE.frame is None)
            scene.render.fps-=1
            p.colliders[0].collider_object.location.x+=.1;bpy.context.view_layer.update();cache.playback_tick()
            check('collider_change_marks_stale',cache.STATE.frame is None)
            p.colliders[0].collider_object.location.x-=.1;bpy.context.view_layer.update()
            runtime.initialize(scene)
            check('live_reset_releases_cache',cache.STATE.reader is None and cache.STATE.handler is None and not bpy.app.timers.is_registered(cache.playback_tick))
            cache.start_bake(scene);job=cache.STATE.job
            bpy.app.timers.unregister(cache.bake_tick);job.advance();partial=p.cache_path;cache.stop_bake()
            check('cancel_preserves_completed_frames',CacheReader(partial).meta['status']=='CANCELLED' and len(CacheReader(partial).meta['frames'])==1)
            check('cancel_frees_gpu_and_timer',job.solver is None and not bpy.app.timers.is_registered(cache.bake_tick))
            check('new_bake_does_not_replace_old',partial!=path and CacheReader(path).meta['status']=='COMPLETE')
            scene.frame_set(3);cache.load_cache(scene)
            check('partial_cache_loads',cache.STATE.frame==3)
            runtime.before_undo(None)
            check('undo_cleans_cache',cache.STATE.fields is None and cache.STATE.handler is None)
            cache.start_bake(scene);job=cache.STATE.job
            bpy.app.timers.unregister(cache.bake_tick);p.turbulence_seed+=1;cache.bake_tick()
            check('edit_during_bake_fails_safely',cache.STATE.job is None and CacheReader(p.cache_path).meta['status']=='FAILED')
            p.turbulence_seed-=1;p.cache_path=path;scene.frame_set(6);cache.load_cache(scene)
            cached=Path(path)/'frame_5.fxc';cached.write_bytes(b'broken')
            scene.frame_set(5);cache.playback_tick()
            check('corrupt_frame_hides_preview',cache.STATE.frame is None and not cache.STATE.fields.fields)
            runtime.before_load(None)
            check('file_load_cleans_cache',cache.STATE.reader is None and cache.STATE.handler is None)
            # Completed I/O + uploads; warm and repeat. Every case is simulated and read back.
            for n in (32,64,128):
                p.resolution=str(n);p.cache_start=1;p.cache_end=4 if n==128 else 12;scene.frame_set(1)
                cache.start_bake(scene);job=cache.STATE.job;bpy.app.timers.unregister(cache.bake_tick)
                began=perf_counter()
                while not job.advance():pass
                seconds=perf_counter()-began;job.close();cache.STATE.job=None
                cache.load_cache(scene);costs=[]
                for _ in range(2):
                    for frame in range(1,p.cache_end+1):
                        scene.frame_set(frame);begin=perf_counter();cache.update_playback()
                        # Explicit readback completes upload before elapsed measurement.
                        texture=cache.STATE.fields.preview_field('DENSITY')
                        texture.read()  # GPU completion without Python conversion of every voxel
                        costs.append((perf_counter()-begin)*1000)
                report['timings'].append(dict(grid=n,channels=5,frames=p.cache_end,bake_seconds=seconds,
                    disk_bytes=sum(f.stat().st_size for f in Path(p.cache_path).iterdir()),
                    load_median_ms=median(costs),load_max_ms=max(costs)))
                cache.release_playback()
            report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        runtime.shutdown();objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:
            data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if data and data.users==0 and isinstance(data,bpy.types.Mesh):bpy.data.meshes.remove(data)
        (ROOT/'test-results/cache-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_CACHE_VALIDATION',report['status'],report.get('traceback',''))
    return report

if __name__=='__main__':run_suite()
