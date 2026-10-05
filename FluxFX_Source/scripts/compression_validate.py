"""Graphical GPU lossless cache comparison and warm filesystem I/O benchmark."""
from pathlib import Path
from statistics import median
from time import perf_counter
import json,tempfile,traceback
import bpy
from fluxfx.blender import cache,runtime
from fluxfx.blender.collider import create_collider
from fluxfx.blender.emitter import create_additional_emitter
from fluxfx.backend.cache import capture,CachedFields
from fluxfx.physics.cache import CacheReader
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    report=dict(status='RUNNING',tests=[],timings=[],blender=bpy.app.version_string,
                build=bpy.app.build_hash.decode())
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Compression Test')
    bpy.context.window.scene=scene;p=scene.fluxfx;p.show_preview=False
    def check(name,condition):
        assert condition,name
        report['tests'].append(dict(name=name,status='PASS'))
    try:
        with tempfile.TemporaryDirectory(prefix='fluxfx-compression-') as directory:
            p.cache_directory=directory;p.combustion_enabled=True;p.heat_source_rate=1000
            p.turbulence_strength=2;p.source_mode='MANUAL'
            wall=create_collider(scene,'BOX');wall.location=(0,0,.1)
            create_additional_emitter(scene);bpy.context.view_layer.update()
            for n in (32,64,128):
                p.resolution=str(n);p.cache_start=1;p.cache_end=8
                raw_reader=None;expected=None
                for compressed in (False,True):
                    p.cache_compress=compressed;scene.frame_set(1)
                    start=perf_counter();cache.start_bake(scene);job=cache.STATE.job
                    bpy.app.timers.unregister(cache.bake_tick)
                    while not job.advance():pass
                    seconds=perf_counter()-start
                    last=capture(job.solver);job.close();cache.STATE.job=None
                    reader=CacheReader(p.cache_path)
                    if not compressed:raw_reader=reader;expected=last
                    else:
                        check(f'{n}_all_frame_checksums_match_raw',all(reader.meta['frames'][f]['crc32']==r['crc32'] for f,r in raw_reader.meta['frames'].items()))
                        check(f'{n}_all_fields_bit_exact',all(list(reader.read(8)[k])==v for k,v in expected.items()))
                        check(f'{n}_encoded_size_never_exceeds_raw',all(r['bytes']<=r['raw_bytes'] for r in reader.meta['frames'].values()))
                        check(f'{n}_compressed_format',reader.meta['format']=='fluxfx-playback-2' and any(r['codec']=='ZLIB' for r in reader.meta['frames'].values()))
                    adapter=CachedFields(reader.grid);costs=[]
                    for _ in range(2):
                        for f in range(1,9):
                            begin=perf_counter();adapter.upload(reader.read(f),'DENSITY')
                            adapter.texture.read();costs.append((perf_counter()-begin)*1000)
                    if compressed:
                        check(f'{n}_gpu_roundtrip',all(adapter.device.read(adapter.preview_field(k),reader.grid.shape)==v for k,v in expected.items()))
                    adapter.close()
                    report['timings'].append(dict(grid=n,compressed=compressed,frames=8,channels=5,
                        bake_seconds=seconds,frame_bytes=sum(r['bytes'] for r in reader.meta['frames'].values()),
                        load_upload_median_ms=median(costs),load_upload_max_ms=max(costs)))
                scene.frame_set(8);cache.load_cache(scene)
                p.cache_compress=False;cache.update_playback()
                check(f'{n}_compression_control_does_not_stale_cache',cache.STATE.frame==8)
                cache.release_playback()
            p.resolution='16';p.cache_compress=True;p.cache_end=3
            cache.start_bake(scene);job=cache.STATE.job;bpy.app.timers.unregister(cache.bake_tick)
            job.advance();cache.stop_bake();reader=CacheReader(p.cache_path)
            check('compressed_cancel_prefix_readable',reader.meta['status']=='CANCELLED' and reader.read(1)['DENSITY'][0]==0)
            scene.frame_set(1);cache.load_cache(scene)
            (reader.path/'frame_1.fxc').write_bytes(b'corrupt');cache.STATE.frame=None;cache.playback_tick()
            check('compressed_corruption_clears_preview',cache.STATE.frame is None and not cache.STATE.fields.fields)
            report['status']='PASS'
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        runtime.shutdown();objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
        (ROOT/'test-results/compression-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_COMPRESSION',report['status'],report.get('traceback',''))
    return report

if __name__=='__main__':run_suite()
