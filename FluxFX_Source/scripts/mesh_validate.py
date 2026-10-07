"""Graphical Blender mesh SDF oracles and smoke/fire exclusion tests."""
from pathlib import Path
from math import sqrt,isfinite
from time import perf_counter
import json,traceback
import bpy
from fluxfx.physics.mesh import MeshCollider
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.collision import primitive,raster_reference
from fluxfx.backend.mesh_sdf import build_sdf
from fluxfx.backend.projected import DenseProjectedSmoke
ROOT=Path(__file__).resolve().parents[1]

def run_suite(gpu_test=True):
    report={'status':'RUNNING','tests':[],'builds':[]};solver=None
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Mesh Tests');bpy.context.window.scene=scene
    def check(name,condition,**details):
        assert condition,(name,details)
        report['tests'].append(dict(name=name,status='PASS',**details))
    def descriptor(obj):
        m=obj.data;m.calc_loop_triangles()
        return MeshCollider(tuple(tuple(obj.matrix_world@v.co) for v in m.vertices),tuple(tuple(t.vertices) for t in m.loop_triangles))
    try:
        grid=GridSpec((32,)*3)
        bpy.ops.mesh.primitive_cube_add(size=.4,location=(.5,.5,.5));cube=bpy.context.object;bpy.context.view_layer.update();box=descriptor(cube)
        values,stats=build_sdf(grid,box);report['builds'].append(dict(name='box',**stats))
        mask=[float(v<=0) for v in values]
        check('box_mask_matches_analytic',mask==raster_reference(grid,(primitive('BOX',(.5,)*3,(.2,)*3),)))
        error=0
        for i,d in enumerate(values):
            p=((i%32+.5)/32,((i//32)%32+.5)/32,(i//1024+.5)/32)
            q=[abs(v-.5)-.2 for v in p]
            expected=sqrt(sum(max(v,0)**2 for v in q))+min(max(q),0)
            error=max(error,abs(d-expected))
        check('box_signed_distance_oracle',error<1e-6,error=error)
        reversed_mesh=MeshCollider(box.vertices,tuple(tuple(reversed(t)) for t in box.triangles))
        reverse,_=build_sdf(grid,reversed_mesh)
        check('reversed_normals_preserve_sign',all((a<0)==(b<0) for a,b in zip(values,reverse)))
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=16,radius=.2,location=(.5,.5,.5));sphere=bpy.context.object;bpy.context.view_layer.update();sphere_mesh=descriptor(sphere)
        sphere_values,stats=build_sdf(grid,sphere_mesh);report['builds'].append(dict(name='sphere',**stats))
        sphere_error=max(abs(d-(sqrt(sum((v-.5)**2 for v in ((i%32+.5)/32,((i//32)%32+.5)/32,(i//1024+.5)/32)))-.2)) for i,d in enumerate(sphere_values))
        check('curved_sphere_distance',sphere_error<.005,error=sphere_error)
        bpy.ops.mesh.primitive_torus_add(major_segments=32,minor_segments=12,major_radius=.23,minor_radius=.09,location=(.5,.5,.5));torus=bpy.context.object;bpy.context.view_layer.update();torus_mesh=descriptor(torus)
        torus_values,stats=build_sdf(grid,torus_mesh);report['builds'].append(dict(name='torus',**stats))
        errors=[];sign_errors=0
        for i,d in enumerate(torus_values):
            x,y,z=(i%32+.5)/32-.5,((i//32)%32+.5)/32-.5,(i//1024+.5)/32-.5
            truth=sqrt((sqrt(x*x+y*y)-.23)**2+z*z)-.09
            errors.append(abs(truth-d))
            if abs(truth)>.006 and (truth<0)!=(d<0):sign_errors+=1
        check('concave_torus_distance',max(errors)<.006,error=max(errors))
        check('concave_torus_sign',sign_errors==0,count=sign_errors)
        check('torus_hole_stays_fluid',torus_values[16+32*(16+32*16)]>0)
        thin=MeshCollider(tuple((x,y,.5+(z-.5)*.09) for x,y,z in box.vertices),box.triangles)
        thin_values,stats=build_sdf(grid,thin)
        check('thin_feature_warning',bool(stats['warnings']) and any(v<0 for v in thin_values))
        for name,bad in [('open',MeshCollider(box.vertices,box.triangles[:-1])),('degenerate',MeshCollider(box.vertices,((0,0,1),)))]:
            try:build_sdf(grid,bad);rejected=False
            except ValueError:rejected=True
            check(name+'_mesh_rejected',rejected)
        if not gpu_test:
            report["status"]="PASS"
            return report
        settings=PressureSettings(combustion_enabled=True,fuel_source_rate=1,heat_source_rate=1000,source_rate=1,
            source_center=(.5,.5,.5),source_radius=.35,ignition_temperature=10,scalar_advection='MACCORMACK',velocity_advection='MACCORMACK')
        solver=DenseProjectedSmoke(grid,settings,colliders=(torus_mesh,primitive('SPHERE',(.25,.25,.25),(.08,)*3)))
        solver.reset(seed=False)
        for _ in range(20):solver.step(.01)
        actual=solver.device.read(solver.solids.mask,grid.shape)
        check('mesh_and_primitive_union',all(m==(1. if d<0 or a else 0.) for m,d,a in zip(actual,torus_values,raster_reference(grid,(primitive('SPHERE',(.25,.25,.25),(.08,)*3),)))))
        fields=[solver.read_density(),solver.read_temperature(),solver.device.read(solver.combustion.fuel,grid.shape),solver.device.read(solver.combustion.flame,grid.shape)]
        check('smoke_heat_fuel_flame_exclusion',all(v==0 for f in fields for v,m in zip(f,actual) if m))
        check('fields_finite_and_active',all(isfinite(v) for f in fields+list(solver.read_velocity()) for v in f) and max(fields[0])>0)
        check('collision_preview_uses_resolved_mask',solver.preview_field('COLLISION') is solver.solids.mask)
        check('sdf_gpu_storage_count',solver.solids.allocated_bytes==8*32**3)
        try:DenseProjectedSmoke(grid,PressureSettings(moving_colliders=True),colliders=(box,));rejected=False
        except ValueError:rejected=True
        check('moving_mesh_rejected',rejected)
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        if solver:solver.close()
        objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:
            mesh=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if mesh.users==0:bpy.data.meshes.remove(mesh)
        (ROOT/'test-results/mesh-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_MESH',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
