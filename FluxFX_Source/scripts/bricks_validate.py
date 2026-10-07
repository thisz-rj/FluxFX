"""Run inside graphical Blender: native brick correctness and 8³/16³ diagnostics."""
from pathlib import Path
import gc,json,time,traceback
from fluxfx.native import BrickPool,fluxfx_core
ROOT=Path(__file__).resolve().parents[1]

def run():
    report=dict(status='RUNNING',tests=[],benchmarks=[])
    def check(name,condition):
        assert condition,name
        report['tests'].append(dict(name=name,status='PASS'))
    def rejects(name,fn):
        try:fn()
        except (ValueError,RuntimeError,OverflowError,TypeError):check(name,True)
        else:raise AssertionError(name)
    baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
    try:
        for side,cap,budget in [(4,8,2**20),(8,0,2**20),(8,262145,2**20),(16,128,2**20),(8,8,1),(8,8,2**64)]:
            rejects('invalid_'+str((side,cap,budget)),lambda:BrickPool(side,cap,budget))
        check('invalid_construction_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
        for side in (8,16):
            with BrickPool(side,8,2**20) as pool:
                check(f'{side}_empty_dispatch',pool.probe()['status']=='PASS')
                center=pool.activate(0,0,0)
                check(f'{side}_idempotent',pool.activate(0,0,0)==center and pool.stats()['active_bricks']==1)
                coords=[(-1,0,0),(1,0,0),(0,-1,0),(0,1,0),(0,0,-1),(0,0,1)]
                neighbors=tuple(pool.activate(*c) for c in coords)
                check(f'{side}_six_neighbors',pool.neighbors(0,0,0)==neighbors)
                check(f'{side}_active_gpu_neighbor_dispatch',pool.probe(3)['status']=='PASS')
                check(f'{side}_deactivation',pool.deactivate(1,0,0) and not pool.deactivate(1,0,0))
                check(f'{side}_missing_neighbor',pool.neighbors(0,0,0)[1]==-1)
                check(f'{side}_slot_reuse',pool.activate(7,8,9)==neighbors[1])
                check(f'{side}_reused_gpu_dispatch',pool.probe()['status']=='PASS')
                pool.activate(1048575,-1048576,0)
                check(f'{side}_boundary_neighbor',pool.neighbors(1048575,-1048576,0)==(-1,)*6)
                rejects(f'{side}_exhaustion',lambda:pool.activate(99,99,99))
                rejects(f'{side}_coordinate_overflow',lambda:pool.activate(2**40,0,0))
                rejects(f'{side}_coordinate_bounds',lambda:pool.activate(1048576,0,0))
                rejects(f'{side}_noninteger',lambda:pool.activate(.5,0,0))
                rejects(f'{side}_bad_repeat',lambda:pool.probe(0))
                check(f'{side}_exhaustion_preserves_topology',pool.stats()['active_bricks']==8 and pool.lookup(99,99,99)==-1)
            check(f'{side}_close_releases',pool.stats()['resident_bytes']==0)
            rejects(f'{side}_closed_query',lambda:pool.lookup(0,0,0))
            pool.close()
        with BrickPool(8,8,2**20) as pool:
            pool.activate_box(0,0,0,2,2,2)
            rejects('atomic_box_exhaustion',lambda:pool.activate_box(1,0,0,2,2,2))
            check('atomic_box_unchanged',pool.stats()['active_bricks']==8 and pool.lookup(2,0,0)==-1)
            pool.activate_box(0,0,0,2,2,2)
            check('duplicate_box_idempotent',pool.stats()['active_bricks']==8)
        pool=BrickPool(8,8,2**20);del pool;gc.collect()
        check('capsule_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
        # Identical 112³ occupied voxel box in a conceptual 256³ domain (8.374%).
        # Reserve identical scalar payload capacity (8 MiB), plus actual topology bytes.
        for scenario,offset in (("aligned",0),("shifted",8)):
            for side,capacity in ((8,4096),(16,512)):
                budget=(capacity*(side**3*4+28)+255)//256*256
                start=time.perf_counter()
                with BrickPool(side,capacity,budget) as pool:
                    setup_ms=(time.perf_counter()-start)*1000
                    lower=offset//side;extent=(offset+112+side-1)//side-lower
                    start=time.perf_counter();pool.activate_box(lower,lower,lower,extent,extent,extent)
                    activation_ms=(time.perf_counter()-start)*1000
                    warmup=pool.probe(1)
                    samples=[pool.probe(8) for _ in range(3)]
                    check(f'{scenario}_{side}_benchmark_exact',warmup['status']=='PASS' and all(s['status']=='PASS' for s in samples))
                    stats=pool.stats()
                    check(f'{scenario}_{side}_matching_work',stats['active_voxels']==(extent*side)**3)
                    report['benchmarks'].append(dict(scenario=scenario,stats=stats,setup_ms=setup_ms,activation_ms=activation_ms,
                        conceptual_domain=256,occupied_voxel_box=112,offset=offset,occupancy=(112/256)**3,
                        allocated_brick_occupancy=stats['active_voxels']/256**3,
                        warmup=warmup,samples=samples))
        check('all_gpu_resources_released',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
        report['status']='PASS'
    except Exception:
        report['status']='FAIL';report['error']=traceback.format_exc()
    (ROOT/'test-results').mkdir(exist_ok=True)
    (ROOT/'test-results/bricks-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_BRICKS',report['status'],len(report['tests']))
    return report

if __name__=='__main__':run()
