"""GPU numerical reference tests for transport, confinement and calibrated sources."""
from pathlib import Path
from dataclasses import replace
import json,math
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.mac import VELOCITY_NAMES,FACE_OFFSETS
    from fluxfx.backend.timestep import AdaptiveTimestep
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.emission import Source,Emission
    report={'status':'RUNNING','tests':[]};solver=controller=None
    def check(name,condition,**metrics):
        assert condition,(name,metrics)
        report['tests'].append(dict(name=name,status='PASS',**metrics))
    try:
        n=32;grid=GridSpec((n,)*3);dt=1/60;speed=.2
        settings=PressureSettings(velocity=(0,0,0),angular_speed=0,source_rate=0,heat_source_rate=0,
            initial_temperature=0,thermal_lift=0,density_weight=0,dissipation=0,cooling=0)
        solver=DenseProjectedSmoke(grid,settings);device=solver.device
        constant=[]
        for axis,shape in enumerate(grid.face_shapes):constant.append(device.texture(shape,[speed if axis==0 else 0.]*math.prod(shape),nonnegative=False))
        velocities=dict(zip(VELOCITY_NAMES,constant))
        coordinates=[((x+.5)/n,(y+.5)/n,(z+.5)/n) for z in range(n) for y in range(n) for x in range(n)]
        def gaussian(p,c):return math.exp(-sum((v-center)**2 for v,center in zip(p,c))/(2*.05**2))
        initial=[gaussian(p,(.3,.5,.5)) for p in coordinates]
        reference=[gaussian(p,(.5,.5,.5)) for p in coordinates]
        errors={};peaks={}
        for mode in ('SEMI_LAGRANGIAN','MACCORMACK'):
            front=device.texture(grid.shape,initial);back=device.texture(grid.shape)
            for _ in range(60):
                correction=(solver.detail.transport(front,velocities,dt) if mode=='MACCORMACK' else {'predictorField':front,'reverseField':front})
                uniforms=solver._source_uniforms()|{'cellCount':grid.shape,'dt':dt,'sourceStart':settings.source_center,
                    'sourceRate':0.,'dissipation':0.,'correctedTransport':float(mode=='MACCORMACK'),'sourceProfile':0.,'targetDensity':-1.}
                device.dispatch(solver._closed_scalar,back,grid.shape,uniforms,front,sources=velocities|correction)
                front,back=back,front
            values=device.read(front,grid.shape)
            errors[mode]=sum(abs(a-b) for a,b in zip(values,reference))/len(values)
            peaks[mode]=max(values)
            check('bounded_gaussian_'+mode,min(values)>=-1e-6 and max(values)<=max(initial)+1e-6,peak=max(values),l1_error=errors[mode])
        check('corrected_transport_reduces_reference_error',errors['MACCORMACK']<.7*errors['SEMI_LAGRANGIAN'],error_ratio=errors['MACCORMACK']/errors['SEMI_LAGRANGIAN'])
        # Corrected transport must support signed temperature and not apply sources twice.
        solver.update_settings(replace(settings,scalar_advection='MACCORMACK',source_rate=2,heat_source_rate=-30))
        solver.reset(seed=False);solver.step(.04)
        rho=solver.read_density();heat=solver.read_temperature()
        check('signed_heat_and_single_injection',min(rho)>=0 and min(heat)<0 and max(abs(t+15*d) for d,t in zip(rho,heat))<2e-5)
        # Exact target/solid profile from an empty zero-velocity field.
        solver.update_settings(replace(settings,scalar_advection='MACCORMACK',density_mode='TARGET',source_profile='SOLID',source_center=(.5,)*3,source_radius=.2,source_rate=1))
        solver.reset(seed=False);solver.step(.04);first=solver.read_density();solver.step(.04)
        expected=[float(sum((v-.5)**2 for v in p)<.2**2) for p in coordinates]
        check('solid_target_matches_sphere',max(abs(a-b) for a,b in zip(first,expected))<1e-6)
        check('target_does_not_accumulate',max(abs(a-b) for a,b in zip(first,solver.read_density()))<1e-6)
        # Mixed targets and additive sources are list-order independent.
        records=[Source((.5,)*3,.2,1,0,Emission((.5,)*3),'TARGET','SOLID'),Source((.5,)*3,.2,2,0,Emission((.5,)*3),'RATE','SOFT')]
        solver.reset(seed=False);solver.step(.04,sources=records);a=solver.read_density()
        solver.reset(seed=False);solver.step(.04,sources=records[::-1]);b=solver.read_density()
        check('mixed_source_order_independent',max(abs(x-y) for x,y in zip(a,b))<1e-6)
        # Uniform solid-body rotation: curl=(0,0,2), no confinement in the interior.
        components=[]
        for axis,shape in enumerate(grid.face_shapes):
            offset=FACE_OFFSETS[axis];values=[]
            for z in range(shape[2]):
                for y in range(shape[1]):
                    for x in range(shape[0]):
                        p=tuple((c+o)/n for c,o in zip((x,y,z),offset))
                        values.append((-(p[1]-.5),p[0]-.5,0)[axis])
            components.append(values)
        fields=[device.texture(shape,values,nonnegative=False) for shape,values in zip(grid.face_shapes,components)]
        outputs=[device.texture(shape) for shape in grid.face_shapes]
        solver.detail.confine(fields,outputs,.04,4,2)
        buffer=solver.detail.curl.read();buffer.dimensions=(4*n**3,);curl=list(buffer)
        interior=[((z*n+y)*n+x)*4 for z in range(3,n-3) for y in range(3,n-3) for x in range(3,n-3)]
        check('analytic_solid_rotation_curl',max(abs(curl[i+2]-2) for i in interior)<1e-5 and max(abs(curl[i]) for i in interior)<1e-5)
        delta=[]
        for axis,shape in enumerate(grid.face_shapes):
            values=device.read(outputs[axis],shape)
            delta.extend(abs(values[(z*shape[1]+y)*shape[0]+x]-components[axis][(z*shape[1]+y)*shape[0]+x]) for z in range(4,n-4) for y in range(4,n-4) for x in range(4,n-4))
        check('constant_curl_has_no_interior_force',max(delta)<1e-6)
        # Nonuniform rotation activates a bounded, finite force.
        components=[[v*(1+.5*math.sin(i*.1)) for i,v in enumerate(values)] for values in components]
        fields=[device.texture(shape,values,nonnegative=False) for shape,values in zip(grid.face_shapes,components)]
        solver.detail.confine(fields,outputs,.04,20,.5)
        delta=[]
        for axis,shape in enumerate(grid.face_shapes):delta.extend(abs(a-b) for a,b in zip(device.read(outputs[axis],shape),components[axis]))
        check('confinement_force_is_active_and_bounded',max(delta)>.0001 and max(delta)<=.04*.5+1e-6,max_velocity_delta=max(delta))
        solver.update_settings(replace(settings,scalar_advection='MACCORMACK',vorticity_strength=4,vorticity_limit=.5))
        solver.reset(seed=False);solver.upload_velocity(components);solver.step(.01)
        fields=solver.read_velocity()
        check('confinement_projected_finite',all(math.isfinite(v) for f in fields for v in f) and solver.measure_projection()['ratio']<.1,ratio=solver.measure_projection()['ratio'])
        controller=AdaptiveTimestep(grid,device);solver.reset(seed=False)
        forced=controller.select(solver,.1,.25)['dt'];solver.update_settings(replace(solver.settings,vorticity_strength=0))
        unforced=controller.select(solver,.1,.25)['dt']
        check('adaptive_bounds_confinement_acceleration',forced<unforced)
        steps=solver.steps;solver.update_settings(replace(solver.settings,scalar_advection='SEMI_LAGRANGIAN'));check('detail_controls_are_live',solver.steps==steps)
        report['status']='PASS'
    except Exception as exc:
        report['status']='FAIL';report['error']=repr(exc);raise
    finally:
        if controller:controller.close()
        if solver:solver.close();check('detail_resources_released',solver.detail is None)
        dest=ROOT/'test-results/detail-validation.json';dest.parent.mkdir(exist_ok=True);dest.write_text(json.dumps(report,indent=2));print(report)
    return report

if __name__=='__main__':run_suite()
