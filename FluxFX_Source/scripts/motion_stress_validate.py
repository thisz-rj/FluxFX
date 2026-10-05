"""Six-second closed-box stress checks for release motion/pressure defaults."""
from pathlib import Path
from time import perf_counter
import json,math
ROOT=Path(__file__).resolve().parents[1]
def run_suite():
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.timestep import AdaptiveTimestep
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.emission import Emission
    report={'status':'RUNNING','tests':[]};solver=control=None
    try:
        for heated in (False,True):
            settings=PressureSettings(velocity=(0,0,0),angular_speed=0,source_center=(.5,.5,.2),source_radius=.09,
                source_rate=1,density_mode='TARGET',source_profile='SOLID',scalar_advection='MACCORMACK',velocity_advection='MACCORMACK',vorticity_strength=4,
                heat_source_rate=100 if heated else 0,initial_temperature=0,thermal_lift=.005 if heated else 0,density_weight=0,dissipation=0,cooling=.5)
            solver=DenseProjectedSmoke(GridSpec((64,)*3),settings);solver.reset(seed=False)
            control=AdaptiveTimestep(solver.grid,solver.device);emission=Emission((.5,.5,.2),(0,0,.5),100)
            start=perf_counter();samples=[];next_sample=1.;courant=0.
            while solver.time<6-1e-9:
                choice=control.select(solver,1/30,.75,emission);dt=min(choice['dt'],6-solver.time)
                courant=max(courant,choice['estimated_courant']);solver.step(dt,emission)
                if solver.time>=next_sample:
                    sample=solver.measure_projection();samples.append(sample);next_sample+=1
                    assert sample['rms_after']<=max(.01,.1*sample['rms_before']),sample
                assert solver.steps<10000 and perf_counter()-start<120,'stress work limit reached'
            velocity=solver.read_velocity();density=solver.read_density();heat=solver.read_temperature()
            assert all(math.isfinite(v) for f in (*velocity,density,heat) for v in f)
            assert min(density)>=-1e-6 and max(density)<=1.0001 and courant<=.75
            report['tests'].append({'name':'heated_64' if heated else 'jet_64','status':'PASS','duration':solver.time,'steps':solver.steps,
                'seconds':perf_counter()-start,'max_abs_velocity':max(abs(v) for f in velocity for v in f),'max_courant_bound':courant,'projection_samples':samples})
            control.close();solver.close();control=solver=None
        report['status']='PASS'
    except Exception as exc:report['status']='FAIL';report['error']=repr(exc);raise
    finally:
        if control:control.close()
        if solver:solver.close()
        (ROOT/'test-results/motion-stress-validation.json').write_text(json.dumps(report,indent=2))
    return report
if __name__=='__main__':run_suite()
