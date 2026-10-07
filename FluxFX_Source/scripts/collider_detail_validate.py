"""0.20 analytic transport and disconnected-pressure GPU checks."""
from pathlib import Path
from dataclasses import replace
import json,math,traceback
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.mac import VELOCITY_NAMES
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.collision import primitive
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    report={'status':'RUNNING','tests':[]};solver=None
    def check(name,condition,**metrics):
        assert condition,(name,metrics)
        report['tests'].append(dict(name=name,status='PASS',**metrics))
    try:
        n=32;grid=GridSpec((n,)*3)
        settings=PressureSettings(velocity=(0,0,0),angular_speed=0,source_rate=0,heat_source_rate=0,
            initial_temperature=0,thermal_lift=0,density_weight=0,dissipation=0,cooling=0)
        solver=DenseProjectedSmoke(grid,settings,colliders=(primitive('SPHERE',(.8,.8,.8),(.1,)*3),))
        device=solver.device
        fields=[device.texture(shape,[.2 if a==0 else 0.]*math.prod(shape),nonnegative=False) for a,shape in enumerate(grid.face_shapes)]
        velocities=dict(zip(VELOCITY_NAMES,fields))
        def gaussian(x,y,z,c):return math.exp(-sum((a-b)**2 for a,b in zip(((x+.5)/n,(y+.5)/n,(z+.5)/n),c))/(2*.05**2))
        initial=[gaussian(x,y,z,(.3,.4,.4)) for z in range(n) for y in range(n) for x in range(n)]
        reference=[gaussian(x,y,z,(.5,.4,.4)) for z in range(n) for y in range(n) for x in range(n)]
        errors={}
        for detailed in (False,True):
            solver.upload(initial)
            front=solver.density;back=solver._back
            for _ in range(60):
                correction=solver.detail.transport(front,velocities,1/60) if detailed else {'predictorField':front,'reverseField':front}
                uniforms=solver._source_uniforms()|{'cellCount':grid.shape,'dt':1/60,'sourceStart':settings.source_center,
                    'sourceRate':0.,'dissipation':0.,'correctedTransport':float(detailed),'sourceProfile':0.,'targetDensity':-1.}
                device.dispatch(solver._closed_scalar,back,grid.shape,uniforms,front,sources=velocities|correction)
                front,back=back,front
            values=device.read(front,grid.shape)
            errors[str(detailed)]=sum(abs(a-b) for a,b in zip(values,reference))/len(values)
            check('bounded_transport_'+str(detailed),min(values)>=0 and max(values)<=max(initial)+1e-6,peak=max(values))
        check('detail_reduces_analytic_error',errors['True']<.7*errors['False'],errors=errors)
        solver.close()
        # Pressure from one disconnected chamber must not affect its neighbor.
        solver=DenseProjectedSmoke(grid,settings,colliders=(primitive('BOX',(.5,.5,.5),(.6,.6,.025)),))
        projector=solver.projector;device=solver.device
        rhs=[float(x-15.5) if z<15 else 0. for z in range(n) for y in range(n) for x in range(n)]
        projector.before=device.texture(grid.shape,rhs,nonnegative=False)
        projector.levels[0]['rhs']=projector.before
        projector.solve_pressure(1.,None)
        pressure=device.read(projector.pressure,grid.shape)
        check('disconnected_pressure_does_not_cross_wall',max(abs(v) for v in pressure[17*n*n:])<1e-7)
        check('pressure_active_in_forced_chamber',max(abs(v) for v in pressure[:15*n*n])>.001)
        check('masked_direct_coarse_solver_used',projector.coarse_matrix is not None,levels=[v['shape'] for v in projector.levels])
        solver.close();solver=None
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        if solver:solver.close()
        (ROOT/'test-results/collider-detail-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_COLLIDER_DETAIL',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
