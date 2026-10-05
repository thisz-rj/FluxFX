"""Graphical GPU tests for rigid moving walls; no Blender scene mutation."""
from pathlib import Path
from dataclasses import replace
from math import prod,isfinite,sin,cos
import json,traceback,time
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.collision import primitive,raster_reference
from fluxfx.physics.collider_motion import MotionPath,Pose,velocity_rows
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.completion import StepCompletion
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    report={'status':'RUNNING','tests':[],'cases':[]};solver=fence=None
    def check(name,condition,**metrics):
        assert condition,(name,metrics)
        report['tests'].append(dict(name=name,status='PASS',**metrics))
    try:
        grid=GridSpec((32,)*3)
        settings=PressureSettings(moving_colliders=True,velocity=(0,0,0),angular_speed=0,
            source_rate=0,heat_source_rate=0,initial_temperature=0,thermal_lift=0,density_weight=0,
            dissipation=0,cooling=0,scalar_advection='MACCORMACK',velocity_advection='MACCORMACK',pressure_iterations=120)
        for shape in ('SPHERE','BOX'):
            initial=primitive(shape,(.35,.5,.5),(.12,.16,.12))
            solver=DenseProjectedSmoke(grid,settings,colliders=(initial,));fence=StepCompletion(solver.device)
            solver.reset(seed=False)
            solver.upload([1.]*prod(grid.shape));solver.upload_temperature([10.]*prod(grid.shape))
            target=primitive(shape,(.65,.5,.5),(.12,.16,.12))
            path=MotionPath((initial,),(target,),.3)
            dt=path.limit_dt(1/60,grid.cell_size)
            oldmask=solver.device.read(solver.solids.mask,grid.shape)
            solver.move_colliders(path.at(dt),dt)
            mask=solver.device.read(solver.solids.mask,grid.shape)
            check(shape+'_updated_mask_matches_reference',mask==raster_reference(grid,path.at(dt)))
            rho=solver.read_density();heat=solver.read_temperature()
            check(shape+'_remap_clears_covered_and_exposed_cells',all(d==0 and t==0 for d,t,m,o in zip(rho,heat,mask,oldmask) if m or o))
            solver.step(dt);fence.wait(solver)
            fluid_peak=wall_error=0.
            for axis,face_shape in enumerate(grid.face_shapes):
                values=solver.device.read(solver._velocity[axis],face_shape)
                walls=solver.device.read(solver.solids.wall_fields[axis],face_shape)
                for z in range(face_shape[2]):
                    for y in range(face_shape[1]):
                        for x in range(face_shape[0]):
                            c=[x,y,z];low=c.copy();low[axis]-=1
                            def solid(q):
                                return any(v<0 or v>=n for v,n in zip(q,grid.shape)) or mask[q[0]+32*(q[1]+32*q[2])]>.5
                            i=x+face_shape[0]*(y+face_shape[1]*z)
                            if solid(c) or solid(low):wall_error=max(wall_error,abs(values[i]-walls[i]))
                            else:fluid_peak=max(fluid_peak,abs(values[i]))
            check(shape+'_wall_pushes_fluid',fluid_peak>.02,fluid_peak=fluid_peak)
            check(shape+'_prescribed_normal_wall_velocity',wall_error<1e-6,error=wall_error)
            check(shape+'_actually_exposes_cells',any(o and not m for o,m in zip(oldmask,mask)))
            metrics=solver.measure_projection()
            check(shape+'_projection_reduces_fluid_divergence',metrics['rms_after']<metrics['rms_before'],projection=metrics)
            elapsed=dt
            while elapsed<.3-1e-8:
                h=min(dt,.3-elapsed)
                solver.move_colliders(path.at(elapsed+h),h);solver.step(h);elapsed+=h
            mask=solver.device.read(solver.solids.mask,grid.shape)
            check(shape+'_arrives_at_target',mask==raster_reference(grid,(target,)))
            check(shape+'_solid_density_and_heat_zero',all(d==0 and t==0 for d,t,m in zip(solver.read_density(),solver.read_temperature(),mask) if m))
            fields=[solver.device.read(tex,s) for tex,s in zip(solver._velocity,grid.face_shapes)]
            check(shape+'_bounded_finite_sweep',all(isfinite(v) and abs(v)<5 for f in fields for v in f))
            solver.move_colliders(solver.solids.colliders,dt);solver.step(dt)
            check(shape+'_stationary_wall_stops',all(abs(v)<1e-6 for tex,s in zip(solver.solids.wall_fields,grid.face_shapes) for v in solver.device.read(tex,s)))
            fence.close();solver.close();solver=fence=None
        # Rotate a nonuniform box using a rigid path, including sharp user jumps.
        a=Pose('BOX',(.5,)*3,(.2,.06,.08),(1.,0,0,0))
        b=Pose('BOX',(.5,)*3,a.size,(cos(.6),0,0,sin(.6)))
        solver=DenseProjectedSmoke(grid,settings,colliders=(a.collider(),))
        solver.reset(seed=False)
        path=MotionPath((a.collider(),),(b.collider(),),.01)
        check('fast_rotation_speed_capped',path.speed<=2.000001)
        elapsed=0.
        while elapsed<path.duration-1e-8:
            dt=path.limit_dt(min(1/60,path.duration-elapsed),grid.cell_size)
            solver.move_colliders(path.at(elapsed+dt),dt);solver.step(dt);elapsed+=dt
        check('rotated_box_mask_matches_reference',solver.device.read(solver.solids.mask,grid.shape)==raster_reference(grid,(b.collider(),)))
        check('rotation_moves_fluid',max(abs(v) for f in solver.read_velocity() for v in f)>.02)
        try:solver.move_colliders((primitive('BOX',(.5,)*3,(.3,.06,.08)),),.01);rejected=False
        except ValueError:rejected=True
        check('resize_rejected',rejected)
        solver.close();solver=None
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        if fence:fence.close()
        if solver:solver.close()
        (ROOT/'test-results/moving-collider-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_MOVING_COLLIDER',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
