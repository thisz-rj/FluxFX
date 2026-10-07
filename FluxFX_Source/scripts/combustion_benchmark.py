"""Completed GPU fire stepping and basic flame preview pixel checks."""
from pathlib import Path
from time import perf_counter
from statistics import median
from math import exp,isfinite
import json,traceback
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.completion import StepCompletion
from fluxfx.backend.timestep import AdaptiveTimestep
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    report={'status':'RUNNING','cases':[],'tests':[]};solver=controller=fence=None
    try:
        import bpy,gpu
        from mathutils import Matrix
        from fluxfx.blender.scene_preview import ScenePreview
        renderer=ScenePreview();target=gpu.types.GPUOffScreen(256,256,format='RGBA32F')
        transform=Matrix(((.5,0,0,.5),(0,0,1.,.5),(0,.5,0,.5),(0,0,0,1)))
        def render(texture,mode):
            with target.bind():
                fb=gpu.state.active_framebuffer_get();fb.clear(color=(0,0,0,0))
                renderer.render(texture,transform,3,thermal=mode)
                buf=fb.read_color(0,0,256,256,4,0,'FLOAT');buf.dimensions=256*256*4
                return list(buf)
        def save(pixels,name):
            img=bpy.data.images.new(name,256,256,alpha=True,float_buffer=True)
            try:
                pixels=[v if i%4!=3 else 1. for i,v in enumerate(pixels)]
                img.pixels.foreach_set(pixels);img.filepath_raw=str(ROOT/'test-results'/name);img.file_format='PNG';img.save()
            finally:bpy.data.images.remove(img)
        try:
            for n in (32,64):
                grid=GridSpec((n,)*3)
                settings=PressureSettings(combustion_enabled=True,fuel_source_rate=1,heat_source_rate=1000,
                    source_rate=0,initial_temperature=0,scalar_advection='MACCORMACK',velocity_advection='MACCORMACK')
                solver=DenseProjectedSmoke(grid,settings);solver.reset(seed=False)
                fence=StepCompletion(solver.device);controller=AdaptiveTimestep(grid,solver.device)
                solver.step(.001);fence.wait(solver);solver.reset(seed=False)
                costs=[];begin=perf_counter()
                for frame in range(120):
                    start=perf_counter();end=(frame+1)/30
                    while end-solver.time>1e-6:
                        dt=controller.select(solver,min(1/30,end-solver.time),.75)['dt']
                        solver.step(dt);fence.wait(solver)
                    costs.append((perf_counter()-start)*1000)
                wall=perf_counter()-begin
                fuel=solver.device.read(solver.combustion.fuel,grid.shape);flame=solver.device.read(solver.combustion.flame,grid.shape)
                heat=solver.read_temperature();density=solver.read_density()
                assert all(isfinite(v) for f in (fuel,flame,heat,density,*solver.read_velocity()) for v in f)
                assert min(fuel)>=0 and min(density)>=0 and max(flame)>0 and max(density)>0
                case=dict(resolution=n,simulation_seconds=solver.time,wall_seconds=wall,speed=solver.time/wall,
                    median_frame_ms=median(costs),p95_frame_ms=sorted(costs)[113],steps=solver.steps,
                    peak_fuel=max(fuel),peak_flame=max(flame),peak_heat=max(heat),peak_density=max(density),status='PASS')
                report['cases'].append(case)
                if n==64:
                    save(render(solver.combustion.flame,2),'combustion-flame.png')
                    save(render(solver.density,0),'combustion-smoke.png')
                    uniform=solver.device.texture((8,)*3,[1.]*512)
                    pixels=render(uniform,2);i=4*(128+256*128);alpha=1-exp(-3)
                    expected=[alpha*c for c in (1.,.315,.12)]+[alpha]
                    error=max(abs(a-b) for a,b in zip(pixels[i:i+4],expected))
                    assert error<1e-4,error
                    report['tests'].append(dict(name='flame_preview_pixel_oracle',error=error,status='PASS'))
                    uniform.clear(format='FLOAT',value=(0.,))
                    assert max(abs(v) for v in render(uniform,2))==0
                    report['tests'].append(dict(name='zero_burn_is_transparent',status='PASS'))
                fence.close();controller.close();solver.close();solver=controller=fence=None
            report['status']='PASS'
        finally:target.free()
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        for item in (controller,fence,solver):
            if item:item.close()
        (ROOT/'test-results/combustion-benchmark.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_FIRE_BENCHMARK',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
