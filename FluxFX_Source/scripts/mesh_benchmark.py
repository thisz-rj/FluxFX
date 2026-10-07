"""32/64 cubed static mesh preparation and completed simulation timings."""
from pathlib import Path
from time import perf_counter
from statistics import median
import bpy,json,traceback
from fluxfx.blender.collider import collider_snapshot
from fluxfx.blender import runtime
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.completion import StepCompletion
from fluxfx.backend.timestep import AdaptiveTimestep
from fluxfx.backend.mesh_sdf import build_sdf
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
ROOT=Path(__file__).resolve().parents[1]

def run_suite(gpu_test=True):
    report={'status':'RUNNING','cases':[]};solver=controller=fence=None
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Mesh Benchmark');bpy.context.window.scene=scene
    try:
        bpy.ops.mesh.primitive_torus_add(major_segments=32,minor_segments=12,major_radius=.23,minor_radius=.09,location=(0,0,.5))
        bpy.ops.fluxfx.add_mesh_collider();bpy.context.view_layer.update();mesh=collider_snapshot(scene)[0]
        for n in (32,64):
            grid=GridSpec((n,)*3)
            begin=perf_counter()
            for _ in range(30):collider_snapshot(scene)
            snapshot_ms=(perf_counter()-begin)*1000/30
            if not gpu_test:
                _,stats=build_sdf(grid,mesh);report['cases'].append(dict(resolution=n,snapshot_ms=snapshot_ms,**stats));continue
            settings=PressureSettings(source_rate=2,heat_source_rate=200,initial_temperature=0,
                scalar_advection='MACCORMACK',velocity_advection='MACCORMACK')
            begin=perf_counter();solver=DenseProjectedSmoke(grid,settings,colliders=(mesh,));setup=perf_counter()-begin
            controller=AdaptiveTimestep(grid,solver.device);fence=StepCompletion(solver.device)
            solver.reset(seed=False);solver.step(.001);fence.wait(solver);solver.reset(seed=False)
            costs=[];begin=perf_counter()
            for frame in range(90):
                start=perf_counter();end=(frame+1)/30
                while end-solver.time>1e-6:
                    dt=controller.select(solver,min(1/30,end-solver.time),.75)['dt'];solver.step(dt);fence.wait(solver)
                costs.append((perf_counter()-start)*1000)
            wall=perf_counter()-begin
            rho=solver.read_density();mask=solver.device.read(solver.solids.mask,grid.shape)
            assert all(d==0 for d,m in zip(rho,mask) if m) and max(rho)>0
            report['cases'].append(dict(resolution=n,setup_seconds=setup,mesh=solver.solids.mesh_reports[0],snapshot_ms=snapshot_ms,
                simulation_speed=solver.time/wall,median_frame_ms=median(costs),p95_frame_ms=sorted(costs)[84],
                gpu_bytes=solver.allocated_bytes+controller.allocated_bytes+4,solid_gpu_bytes=solver.solids.allocated_bytes,
                projection=solver.measure_projection()))
            fence.close();controller.close();solver.close();solver=controller=fence=None
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        for item in (fence,controller,solver):
            if item:item.close()
        objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:
            data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if data and data.users==0:bpy.data.meshes.remove(data)
        name='mesh-benchmark' if gpu_test else 'mesh-build-benchmark'
        (ROOT/'test-results'/f'{name}.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_MESH_BENCHMARK',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
