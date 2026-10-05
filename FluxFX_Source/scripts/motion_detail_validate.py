"""0.17 GPU tests: signed MAC transport accuracy and variable-step projection."""
from pathlib import Path
from dataclasses import replace
import json,math
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.pressure import PressureProjector
    from fluxfx.backend.multigrid import MultigridPressureProjector
    from fluxfx.backend.mac import VELOCITY_NAMES,FACE_OFFSETS
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.pressure_reference import walls
    report={'status':'RUNNING','tests':[]};solver=None;projector=None
    def check(name,ok,**data):
        if not ok:raise AssertionError((name,data))
        report['tests'].append({'name':name,'status':'PASS',**data})
    try:
        grid=GridSpec((32,)*3);n=32;dt=1/60
        settings=PressureSettings(velocity=(0,0,0),angular_speed=0,source_rate=0,heat_source_rate=0,thermal_lift=0,density_weight=0)
        solver=DenseProjectedSmoke(grid,settings);device=solver.device
        initial=[];reference=[]
        for axis,shape in enumerate(grid.face_shapes):
            values=[];exact=[]
            for z in range(shape[2]):
                for y in range(shape[1]):
                    for x in range(shape[0]):
                        px=(x+FACE_OFFSETS[axis][0])/n
                        values.append((.2,.1*math.exp(-.5*((px-.3)/.05)**2),-.03)[axis])
                        exact.append((.2,.1*math.exp(-.5*((px-.5)/.05)**2),-.03)[axis])
            initial.append(values);reference.append(exact)
        errors={}
        for mode in ('SEMI_LAGRANGIAN','MACCORMACK'):
            solver.upload_velocity(initial)
            for step in range(60):
                corrected=mode=='MACCORMACK'
                if corrected:solver.detail.transport_velocity(solver._velocity,dt)
                for axis,shape in enumerate(grid.face_shapes):
                    sources=dict(zip(VELOCITY_NAMES,solver._velocity))|{'originalFaceField':solver._velocity[axis],
                        'facePredictor':solver.detail.face_predictor[axis] if corrected else solver._velocity[axis]}
                    device.dispatch(solver._emitting_velocity,solver._velocity_back[axis],shape,
                        solver._face_uniforms(axis)|{'dt':dt,'correctedVelocity':float(corrected),'sourceCenter':(.5,)*3,
                        'sourceStart':(.5,)*3,'sourceRadius':.1,'sourceProfile':0.,'emissionVelocity':(0,0,0),'emissionCoupling':0.},sources=sources)
                solver._velocity,solver._velocity_back=solver._velocity_back,solver._velocity
            values=solver.read_velocity()
            check('signed_constants_'+mode,max(abs(v-.2) for v in values[0])<1e-6 and max(abs(v+.03) for v in values[2])<1e-6)
            check('bounded_shear_'+mode,min(values[1])>=-1e-7 and max(values[1])<=max(initial[1])+1e-7)
            errors[mode]=sum(abs(a-b) for a,b in zip(values[1],reference[1]))/len(values[1])
        check('velocity_correction_reduces_error',errors['MACCORMACK']<.85*errors['SEMI_LAGRANGIAN'],errors=errors,ratio=errors['MACCORMACK']/errors['SEMI_LAGRANGIAN'])
        # Fixed input isolates projection from time integration. An impulse warm start
        # must survive dt changes and improve convergence without extra cold solves.
        for cls in (PressureProjector,MultigridPressureProjector):
            fields=[device.texture(shape,[math.sin(i*.13)*.2 for i in range(math.prod(shape))],nonnegative=False) for shape in grid.face_shapes]
            output=[device.texture(shape) for shape in grid.face_shapes]
            warm=[];cold=[];cold_values=None;warm_values=None
            for strategy in ('LEGACY','IMPULSE'):
                projector=cls(grid,replace(settings,pressure_warm_start=strategy),device)
                for timestep in (.04,.013,.025,.007):
                    projector.project(fields,output,timestep)
                    metrics=projector.metrics()
                    (warm if strategy=='IMPULSE' else cold).append(metrics)
                    check(cls.__name__+'_'+strategy+'_finite_'+str(timestep),math.isfinite(metrics['rms_after']) and metrics['ratio']<.05,ratio=metrics['ratio'])
                    if timestep==.04:
                        vals=[device.read(t,s) for t,s in zip(output,grid.face_shapes)]
                        if strategy=='LEGACY':cold_values=vals
                        else:warm_values=vals
                check(cls.__name__+'_'+strategy+'_walls',tuple(device.read(t,s) for t,s in zip(output,grid.face_shapes))==walls(tuple(device.read(t,s) for t,s in zip(output,grid.face_shapes)),grid))
                projector.reset();check(cls.__name__+'_'+strategy+'_reset',projector.last_dt is None and not projector.ready)
                projector.close();projector=None
            check(cls.__name__+'_cold_equivalent',max(abs(a-b) for aa,bb in zip(cold_values,warm_values) for a,b in zip(aa,bb))<2e-6)
            check(cls.__name__+'_warm_residual_small',warm[-1]['ratio']<.005,warm=warm[-1]['rms_after'],legacy=cold[-1]['rms_after'])
            if cls is PressureProjector:check('variable_dt_avoids_cold_multiplier',warm[-1]['iterations']==80 and cold[-1]['iterations']==320)
        solver.update_settings(replace(settings,velocity_advection='MACCORMACK',scalar_advection='MACCORMACK',vorticity_strength=4))
        solver.reset(seed=False)
        for timestep in (.02,.01,.017):solver.step(timestep)
        check('coupled_detailed_flow_finite',all(math.isfinite(v) for f in solver.read_velocity() for v in f))
        steps=solver.steps;solver.update_settings(replace(solver.settings,velocity_advection='SEMI_LAGRANGIAN'))
        check('motion_switch_is_live',solver.steps==steps)
        report['status']='PASS'
    except Exception as exc:report['status']='FAIL';report['error']=repr(exc);raise
    finally:
        if projector:projector.close()
        if solver:solver.close();check('detail_released',solver.detail is None)
        dest=ROOT/'test-results/motion-detail-validation.json';dest.parent.mkdir(exist_ok=True);dest.write_text(json.dumps(report,indent=2));print(report)
    return report
if __name__=='__main__':run_suite()
