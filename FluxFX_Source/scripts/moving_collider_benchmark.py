"""64-cubed moving-wall completed-step benchmark, excluding viewport drawing."""
from pathlib import Path
from math import sin, cos, isfinite
from statistics import median
from time import perf_counter
import json, traceback
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.collider_motion import Pose, MotionPath
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.completion import StepCompletion
from fluxfx.backend.timestep import AdaptiveTimestep
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    report={'status':'RUNNING','cases':[]};solver=fence=controller=None
    try:
        grid=GridSpec((64,)*3)
        for shape in ('SPHERE','BOX'):
            for detailed in (False,True):
                transport='MACCORMACK' if detailed else 'SEMI_LAGRANGIAN'
                settings=PressureSettings(moving_colliders=True,velocity=(0,0,0),angular_speed=0,
                    scalar_advection=transport,velocity_advection=transport,pressure_iterations=80)
                size=(.12,)*3 if shape=='SPHERE' else (.18,.06,.08)
                def pose(t):
                    return Pose(shape,(.5+.12*sin(2*t),.5,.5),size,(cos(t*.4),0,0,sin(t*.4)))
                solver=DenseProjectedSmoke(grid,settings,colliders=(pose(0).collider(),));solver.reset(seed=False)
                fence=StepCompletion(solver.device);controller=AdaptiveTimestep(grid,solver.device)
                solver.move_colliders(solver.solids.colliders,.001);solver.step(.001);fence.wait(solver)
                costs=[];start=perf_counter();begin_time=solver.time
                for frame in range(60):
                    begin=perf_counter();end=begin_time+(frame+1)/30
                    path=MotionPath(solver.solids.colliders,(pose((frame+1)/30).collider(),),end-solver.time)
                    elapsed=0
                    while end-solver.time>1e-6:
                        dt=controller.select(solver,min(1/30,end-solver.time),.75)['dt']
                        dt=path.limit_dt(dt,grid.cell_size);elapsed+=dt
                        solver.move_colliders(path.at(elapsed),dt);solver.step(dt);fence.wait(solver)
                    costs.append((perf_counter()-begin)*1000)
                wall=perf_counter()-start
                density=solver.read_density();heat=solver.read_temperature();vel=solver.read_velocity()
                mask=solver.device.read(solver.solids.mask,grid.shape)
                assert all(isfinite(v) for f in [density,heat,*vel] for v in f)
                assert all(d==0 and h==0 for d,h,m in zip(density,heat,mask) if m)
                assert min(density)>=0 and max(abs(v) for f in vel for v in f)<5
                report['cases'].append(dict(shape=shape,detailed=detailed,simulation_seconds=solver.time-begin_time,
                    wall_seconds=wall,simulation_speed=(solver.time-begin_time)/wall,median_frame_ms=median(costs),
                    p95_frame_ms=sorted(costs)[56],projection=solver.measure_projection(),status='PASS'))
                controller.close();fence.close();solver.close();solver=fence=controller=None
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        for item in (controller,fence,solver):
            if item:item.close()
        (ROOT/'test-results/moving-collider-benchmark.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_MOVING_BENCHMARK',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
