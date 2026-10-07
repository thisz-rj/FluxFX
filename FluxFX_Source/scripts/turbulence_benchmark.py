"""Matched smoke/fire + mesh runs with turbulence off/on; completed GPU timings."""
from pathlib import Path
from dataclasses import replace
from time import perf_counter
from statistics import median
from math import isfinite
import bpy,json,traceback
from fluxfx.blender.collider import collider_snapshot
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.completion import StepCompletion
from fluxfx.backend.timestep import AdaptiveTimestep
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    report={'status':'RUNNING','cases':[],'tests':[]};solver=fence=ctl=None
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Turbulence Benchmark');bpy.context.window.scene=scene
    try:
        bpy.ops.mesh.primitive_torus_add(major_segments=24,minor_segments=12,major_radius=.22,minor_radius=.07,location=(0,0,.55))
        bpy.ops.fluxfx.add_mesh_collider();bpy.context.view_layer.update();colliders=collider_snapshot(scene)
        for n in (32,64):
            for fire in (False,True):
                baseline=None
                for strength in (0,2):
                    grid=GridSpec((n,)*3)
                    settings=PressureSettings(combustion_enabled=fire,source_rate=0 if fire else 2,
                        heat_source_rate=1000 if fire else 200,initial_temperature=0,
                        turbulence_strength=strength,turbulence_scale=.5,turbulence_mask='HEAT' if fire else 'DENSITY',
                        turbulence_threshold=150 if fire else .2,turbulence_seed=17,
                        scalar_advection='MACCORMACK',velocity_advection='MACCORMACK')
                    solver=DenseProjectedSmoke(grid,settings,colliders=colliders if fire else ())
                    ctl=AdaptiveTimestep(grid,solver.device);fence=StepCompletion(solver.device)
                    solver.reset(seed=False);solver.step(.001);fence.wait(solver);solver.reset(seed=False)
                    costs=[];begin=perf_counter()
                    for frame in range(90):
                        start=perf_counter();end=(frame+1)/30
                        while end-solver.time>1e-6:
                            dt=ctl.select(solver,min(1/30,end-solver.time),.75)['dt'];solver.step(dt);fence.wait(solver)
                        costs.append((perf_counter()-start)*1000)
                    wall=perf_counter()-begin;rho=solver.read_density();heat=solver.read_temperature();velocity=solver.read_velocity()
                    assert all(isfinite(v) for f in (rho,heat,*velocity) for v in f) and min(rho)>=0
                    if solver.solids:
                        mask=solver.device.read(solver.solids.mask,grid.shape)
                        fuel=solver.device.read(solver.combustion.fuel,grid.shape)
                        assert all(v==0 for f in (rho,heat,fuel) for v,m in zip(f,mask) if m)
                    difference=0 if baseline is None else sum(abs(a-b) for a,b in zip(rho,baseline))/len(rho)
                    if strength==0:baseline=rho
                    else:assert difference>1e-5,(n,fire,difference)
                    label=f'{n}-{ "fire-mesh" if fire else "smoke" }-{strength}'
                    report['cases'].append(dict(name=label,grid=n,fire_mesh=fire,strength=strength,speed=solver.time/wall,
                        median_frame_ms=median(costs),p95_frame_ms=sorted(costs)[84],steps=solver.steps,
                        density_difference=difference,extra_turbulence_bytes=solver.turbulence.allocated_bytes,status='PASS'))
                    projection=[sum(rho[x+n*(y+n*z)] for y in range(n))/n for z in range(n) for x in range(n)]
                    (ROOT/f'test-results/turbulence-image-{label}.json').write_text(json.dumps(dict(n=n,density=projection)))
                    fence.close();ctl.close();solver.close();solver=fence=ctl=None
                    (ROOT/'test-results/turbulence-benchmark.json').write_text(json.dumps(report,indent=2))
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        for v in (fence,ctl,solver):
            if v:v.close()
        objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:
            mesh=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if mesh and mesh.users==0:bpy.data.meshes.remove(mesh)
        (ROOT/'test-results/turbulence-benchmark.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_TURBULENCE_BENCHMARK',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
