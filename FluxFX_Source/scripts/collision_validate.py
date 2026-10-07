"""Graphical GPU collision checks. No scene mutation; run after dev_load.py."""
from pathlib import Path
from dataclasses import replace
import json, math, traceback, time
from fluxfx.physics.collision import primitive, raster_reference, Collider
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.emission import Source, Emission
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.timestep import AdaptiveTimestep
from fluxfx.backend.completion import StepCompletion
from fluxfx.backend.mac import VELOCITY_NAMES

ROOT=Path(__file__).resolve().parents[1]


def run_suite(detailed=False):
    report={'status':'RUNNING','tests':[], 'measurements':{}}
    def check(name,condition):
        assert condition,name
        report['tests'].append({'name':name,'status':'PASS'})
    solver=None
    try:
        grid=GridSpec((24,20,16))
        c=math.sqrt(.5)
        rotated=Collider('BOX',((c/.18,c/.18,0,-c/.18),(-c/.1,c/.1,0,0),(0,0,1/.2,-.5/.2)))
        shapes=(primitive('SPHERE',(.35,.5,.5),(.17,)*3),rotated)
        settings=PressureSettings(velocity=(0,0,.5),angular_speed=0,source_rate=2,heat_source_rate=100,
                                  initial_temperature=50,pressure_iterations=240,thermal_lift=0,density_weight=0,
                                  scalar_advection='MACCORMACK' if detailed else 'SEMI_LAGRANGIAN',
                                  velocity_advection='MACCORMACK' if detailed else 'SEMI_LAGRANGIAN')
        solver=DenseProjectedSmoke(grid,settings,colliders=shapes)
        mask=solver.device.read(solver.solids.mask,grid.shape)
        check('gpu_affine_union_matches_reference',mask==raster_reference(grid,shapes))
        check('collider_pressure_uses_impulse',solver.projector.uses_impulse)
        solver.upload([1.0]*math.prod(grid.shape));solver.upload_temperature([-4.0]*math.prod(grid.shape))
        check('upload_density_clears_solids',all(v==0 for m,v in zip(mask,solver.read_density()) if m))
        check('upload_signed_heat_clears_solids',all(v==0 for m,v in zip(mask,solver.read_temperature()) if m))
        solver.step(.01)
        first=solver.measure_projection()
        report["measurements"]["initial_projection"]=first
        check("initial_projection_reduces_divergence",first["ratio"]<.1)
        for _ in range(19):solver.step(.01)
        density=solver.read_density();heat=solver.read_temperature()
        check('no_smoke_or_heat_inside_solids',all(d==0 and h==0 for m,d,h in zip(mask,density,heat) if m))
        check('finite_bounded_scalars',all(math.isfinite(v) for v in density+heat) and min(density)>=0)
        def blocked_max():
            maximum=0.
            for axis,(shape,tex) in enumerate(zip(grid.face_shapes,solver._velocity)):
                values=solver.device.read(tex,shape)
                for z in range(shape[2]):
                    for y in range(shape[1]):
                        for x in range(shape[0]):
                            cell=[x,y,z];low=cell.copy();low[axis]-=1
                            def solid(c):
                                return any(v<0 or v>=n for v,n in zip(c,grid.shape)) or mask[c[0]+grid.shape[0]*(c[1]+grid.shape[1]*c[2])]>0
                            if solid(cell) or solid(low):maximum=max(maximum,abs(values[x+shape[0]*(y+shape[1]*z)]))
            return maximum
        check('zero_normal_velocity_at_solid_faces',blocked_max()<1e-7)
        metrics=solver.measure_projection();report['measurements']['projection']=metrics
        check('masked_projection_reduces_divergence',metrics['ratio'] is not None and metrics['ratio']<1 and metrics['rms_after']<.005)
        solver.close();check('collision_resources_released',solver.solids is None)

        # A full slab separates chambers. Test tracing directly with intentionally
        # cross-wall velocities and a departure > one cell: masking destinations
        # alone would leak into the opposite chamber.
        grid=GridSpec((32,)*3)
        slab=primitive('BOX',(.5,.5,.5),(.6,.6,.025))
        settings=replace(settings,source_rate=0,heat_source_rate=0,initial_temperature=0,dissipation=0)
        solver=DenseProjectedSmoke(grid,settings,colliders=(slab,))
        data=[float(z<15) for z in range(32) for y in range(32) for x in range(32)]
        solver.upload(data)
        velocity=[solver.device.texture(shape,[1.0 if axis==2 else 0.0]*math.prod(shape),nonnegative=False)
                  for axis,shape in enumerate(grid.face_shapes)]
        common=solver._source_uniforms()|{'cellCount':grid.shape,'dt':.1,'sourceStart':settings.source_center,
            'sourceProfile':0.,'sourceRate':0.,'targetDensity':-1.,'correctedTransport':float(detailed),'dissipation':0.}
        correction=solver.detail.transport(solver.density,dict(zip(VELOCITY_NAMES,velocity)),.1) if detailed else {'predictorField':solver.density,'reverseField':solver.density}
        solver.device.dispatch(solver._closed_scalar,solver._back,grid.shape,common,solver.density,
            sources=dict(zip(VELOCITY_NAMES,velocity))|correction)
        values=solver.device.read(solver._back,grid.shape)
        check('large_trace_cannot_cross_slab',max(values[17*32*32:])==0)
        check('upstream_smoke_not_erased',max(values[:14*32*32])>.99)
        # Exercise the table-emitter variants and source overlap with a solid.
        sources=[Source((.5,.5,.5),.2,2,10,Emission((.5,.5,.5),(0,0,1),10))]
        for _ in range(10):solver.step(.01,sources=sources)
        mask=solver.device.read(solver.solids.mask,grid.shape)
        check('emitter_cannot_fill_solid_cells',all(v==0 for m,v in zip(mask,solver.read_density()) if m))
        solver.close()
        # Degenerate domains of fluid: isolated cells and all-solid masks must
        # never divide by a zero pressure diagonal.
        solver=DenseProjectedSmoke(GridSpec((8,)*3),settings,colliders=(primitive('BOX',(.5,)*3,(1,)*3),))
        solver.step(.01)
        check('all_solid_domain_finite_zero',all(v==0 for v in solver.read_density()) and all(v==0 for v in solver.device.read(solver.projector.pressure,(8,)*3)))
        isolated=[1.0]*512;isolated[4+8*(4+8*4)]=0.0
        solver.solids.mask=solver.device.texture((8,)*3,isolated)
        solver.upload([1.0]*512);solver.step(.01)
        check('isolated_fluid_cell_finite',sum(solver.read_density())==1 and all(math.isfinite(v) for v in solver.device.read(solver.projector.pressure,(8,)*3)))
        solver.close();solver=None
        report['status']='PASS'
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        if solver:solver.close()
        (ROOT/'test-results').mkdir(exist_ok=True)
        (ROOT/f'test-results/collision-validation{"-detailed" if detailed else ""}.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_COLLISION_VALIDATION',report['status'],report.get('traceback',''))
    return report

if __name__=='__main__':run_suite()
