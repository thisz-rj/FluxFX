"""P0.9 reproducible main-thread benchmarks in graphical Blender.

No GPU timestamp API is assumed. Synchronized wall samples INCLUDE a dependency
shader and one-float readback. Render samples include one-pixel framebuffer read.
The timing fence consumes all final fields; it does not download volume data.
"""
from pathlib import Path
from time import perf_counter
from statistics import median
from math import ceil,isfinite
import json

ROOT=Path(__file__).resolve().parents[1]


def summarize(values):
    ordered=sorted(values)
    return {'count':len(values),'median_ms':median(values),'p95_ms':ordered[ceil(.95*len(values))-1],
            'min_ms':min(values),'max_ms':max(values),'samples_ms':values}


def run_suite():
    import gpu
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.timestep import AdaptiveTimestep
    from fluxfx.backend.diagnostics import collect
    from fluxfx.physics.config import GridSpec
    from fluxfx.blender.preview import SlicePreview
    from fluxfx.blender import runtime
    runtime.pause()
    report={'status':'RUNNING','diagnostics':collect(True),'sample_count':30,'warmup_steps':5,
            'method':'CPU submission vs synchronized wall including one-float fence readback; not pure GPU timestamps',
            'cases':[]}
    output=ROOT/'test-results/benchmark.json'
    output.parent.mkdir(exist_ok=True)
    def save(): output.write_text(json.dumps(report,indent=2)+'\n')
    save()
    for n in (64,128):
        solver=DenseProjectedSmoke(GridSpec((n,n,n)))
        controller=AdaptiveTimestep(solver.grid,solver.device)
        device=solver.device
        fence=device.kernel('benchmark_fence.glsl',samplers=('densityField','temperatureField','velocityU','velocityV','velocityW','divergenceField'))
        pixel=device.texture((1,1,1))
        def sync(velocities=None):
            vel=solver._velocity if velocities is None else velocities
            device.dispatch(fence,pixel,(1,1,1),sources=dict(zip(
                ('densityField','temperatureField','velocityU','velocityV','velocityW','divergenceField'),
                (solver.density,solver.temperature,*vel,solver.projector.after))))
            value=device.read(pixel,(1,1,1))[0]
            assert isfinite(value)
        case={'grid':n,'field_bytes':solver.allocated_bytes+controller.allocated_bytes}
        try:
            sync()
            baseline=[]
            for _ in range(30):
                start=perf_counter();sync();baseline.append((perf_counter()-start)*1000)
            case['fence_baseline']=summarize(baseline)
            for mode in ('fixed','adaptive'):
                solver.reset();sync()
                start=perf_counter()
                if mode=='adaptive': dt=controller.select(solver,1/30,.75)['dt']
                else: dt=1/30
                solver.step(dt);sync()
                cold=(perf_counter()-start)*1000
                for _ in range(5):
                    if mode=='adaptive': dt=controller.select(solver,1/30,.75)['dt']
                    solver.step(dt);sync()
                wall=[];submit=[];dts=[];iterations=[]
                for _ in range(30):
                    start=perf_counter()
                    if mode=='adaptive': dt=controller.select(solver,1/30,.75)['dt']
                    submission=perf_counter();solver.step(dt)
                    submit.append((perf_counter()-submission)*1000)
                    sync();wall.append((perf_counter()-start)*1000)
                    dts.append(dt);iterations.append(solver.projector.last_iterations)
                case[mode]={'cold_step_wall_ms':cold,'wall':summarize(wall),'solver_submission':summarize(submit),
                            'dt_samples':dts,'pressure_iterations':iterations,'projection':solver.measure_projection()}
            selection=[]
            for _ in range(30):
                start=perf_counter();controller.select(solver,1/30,.75)
                selection.append((perf_counter()-start)*1000)
            case['adaptive_selection_only']=summarize(selection)
            # Fixed snapshot and outputs: isolates pressure solve with its normal warm start.
            solver.projector.project(solver._velocity,solver._velocity_back,1/30);sync(solver._velocity_back)
            pressure=[]
            for _ in range(30):
                start=perf_counter()
                solver.projector.project(solver._velocity,solver._velocity_back,1/30)
                sync(solver._velocity_back);pressure.append((perf_counter()-start)*1000)
            case['pressure_snapshot_wall']=summarize(pressure)
            target=gpu.types.GPUOffScreen(512,512,format='RGBA32F')
            previous=(gpu.state.blend_get(),gpu.state.depth_test_get(),gpu.state.depth_mask_get())
            try:
                renderer=SlicePreview(volume=True)
                with target.bind():
                    gpu.state.blend_set('NONE');gpu.state.depth_test_set('NONE');gpu.state.depth_mask_set(False)
                    shader=renderer.shader;shader.bind()
                    for key,value in {'viewportSize':(512,512),'uiScale':1,'exposure':3,'thermalView':0,
                        'viewRight':(1,0,0),'viewUp':(0,0,1),'viewForward':(0,1,0)}.items():
                        shader.uniform_float(key,value)
                    shader.uniform_sampler('densityField',solver.density)
                    case['render']={}
                    for steps in (64,128,256):
                        shader.uniform_int('raySteps',steps)
                        samples=[]
                        for i in range(35):
                            start=perf_counter();renderer.batch.draw(shader)
                            gpu.state.active_framebuffer_get().read_color(154,178,1,1,4,0,'FLOAT')
                            if i>=5:samples.append((perf_counter()-start)*1000)
                        case['render'][str(steps)]=summarize(samples)
            finally:
                gpu.state.blend_set(previous[0]);gpu.state.depth_test_set(previous[1]);gpu.state.depth_mask_set(previous[2])
                target.free()
            report['cases'].append(case);save()
            print('FLUXFX_BENCHMARK_GRID',n,'fixed',case['fixed']['wall']['median_ms'],'adaptive',case['adaptive']['wall']['median_ms'])
        finally:
            controller.close();solver.close()
            fence=pixel=None
    report['status']='PASS';save()
    print('FLUXFX_BENCHMARK_PASS',str(output))
    return report

if __name__=='__main__': run_suite()
