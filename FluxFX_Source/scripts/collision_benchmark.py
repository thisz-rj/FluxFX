"""64³ completed GPU stepping: common jet scene, with/without static solids."""
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from statistics import median
import json, math, traceback
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.collision import primitive
from fluxfx.physics.emission import Emission
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.timestep import AdaptiveTimestep
from fluxfx.backend.completion import StepCompletion

ROOT=Path(__file__).resolve().parents[1]


def run_suite(names=('none','sphere','box'), iterations=80, pressure_solver='AUTO', detailed=True, label='020', frames=180):
    report={'status':'RUNNING','cases':[],'tests':[]}
    solver=controller=fence=None
    output=ROOT/f'test-results/collision-benchmark-{label}.json'
    try:
        for name in names:
            grid=GridSpec((64,)*3)
            colliders=() if name=='none' else (primitive(name.upper(),(.5,.5,.48),(.15,)*3 if name=='sphere' else (.18,.18,.07)),)
            settings=PressureSettings(velocity=(0,0,0),angular_speed=0,source_center=(.5,.5,.16),source_radius=.08,
                source_rate=3,heat_source_rate=1000,initial_temperature=0,thermal_lift=.05,density_weight=.05,
                pressure_iterations=iterations,pressure_solver=pressure_solver,
                velocity_advection='MACCORMACK' if detailed else 'SEMI_LAGRANGIAN',
                scalar_advection='MACCORMACK' if detailed else 'SEMI_LAGRANGIAN')
            solver=DenseProjectedSmoke(grid,settings,colliders=colliders)
            solver.reset(seed=False)
            controller=AdaptiveTimestep(grid,solver.device)
            fence=StepCompletion(solver.device)
            emission=Emission(settings.source_center,(0,0,1),20)
            solver.step(.001,emission);fence.wait(solver) # compile outside timing
            solver.reset(seed=False)
            costs=[];substeps=[];start=perf_counter()
            for frame in range(1,frames+1):
                target=frame/30;begin=perf_counter();count=0
                while target-solver.time>1e-6:
                    dt=controller.select(solver,min(1/30,target-solver.time),.75,emission)['dt']
                    solver.step(dt,emission);fence.wait(solver);count+=1
                costs.append((perf_counter()-begin)*1000);substeps.append(count)
            wall=perf_counter()-start
            density=solver.read_density();heat=solver.read_temperature()
            mask=solver.device.read(solver.solids.mask,grid.shape) if solver.solids else [0.]*len(density)
            velocity=[solver.device.read(tex,shape) for tex,shape in zip(solver._velocity,grid.face_shapes)]
            ratio=solver.measure_projection()
            case=dict(name=name,pressure_solver=pressure_solver,detailed=detailed,wall_seconds=wall,simulated_seconds=solver.time,simulation_speed=solver.time/wall,
                median_frame_ms=median(costs),p95_frame_ms=sorted(costs)[int(.95*(len(costs)-1))],max_frame_ms=max(costs),
                substeps=sum(substeps),projection=ratio,fields_bytes=solver.allocated_bytes+controller.allocated_bytes+4,
                max_speed_component=max(abs(v) for values in velocity for v in values),
                solid_density_max=max([v for v,m in zip(density,mask) if m] or [0]),
                density_above=sum(density[40*64*64:]),density_total=sum(density))
            # Raw mid-plane values for a numerical comparison figure, not a render.
            preview={'case':name,'n':64,'density':[density[x+64*(32+64*z)] for z in range(64) for x in range(64)],
                     'solid':[mask[x+64*(32+64*z)] for z in range(64) for x in range(64)]}
            (ROOT/f'test-results/collision-slice-{label}-{name}.json').write_text(json.dumps(preview))
            def check(label,value):
                assert value,(name,label,case)
                report['tests'].append({'name':name+'_'+label,'status':'PASS'})
            check('finite_fields',all(math.isfinite(v) for v in density+heat) and all(math.isfinite(v) for f in velocity for v in f))
            check('bounded_flow',case['max_speed_component']<5 and min(density)>=0)
            check('solid_exclusion',case['solid_density_max']==0)
            # A blocked plume needs time to travel around the obstacle.
            check('smoke_reaches_above_obstacle',case['density_above']>1)
            report['cases'].append(case)
            output.write_text(json.dumps(report,indent=2))
            controller.close();fence.close();solver.close();solver=controller=fence=None
        report['status']='PASS'
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        if controller:controller.close()
        if fence:fence.close()
        if solver:solver.close()
        output.write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_COLLISION_BENCHMARK',report['status'],report.get('traceback',''))
    return report

if __name__=='__main__':run_suite()
