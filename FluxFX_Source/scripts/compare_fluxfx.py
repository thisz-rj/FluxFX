"""Graphical Blender half: exactly 60 output frames, adaptive substeps to 2 seconds.

Run after native cases finish: simultaneous workloads would invalidate timings.
Runs one case per timer callback, preserving the user's paused solver and scene.
"""
from pathlib import Path
from dataclasses import replace,asdict
from time import perf_counter
import json,gzip,array,math,resource
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results/comparison'


def positions(case,frame):
    if case=='multiple':return ((.3,.5,.2),(.7,.5,.2))
    if case=='moving':return ((.25+.5*max(0,min(59,frame-1))/59,.5,.2),)
    return ((.5,.5,.2),)


def render_common(device,texture):
    import gpu
    from fluxfx.blender.preview import SlicePreview
    from statistics import median
    target=gpu.types.GPUOffScreen(512,512,format='RGBA32F')
    state=(gpu.state.blend_get(),gpu.state.depth_test_get(),gpu.state.depth_mask_get())
    try:
        renderer=SlicePreview(volume=True)
        with target.bind():
            gpu.state.blend_set('NONE');gpu.state.depth_test_set('NONE');gpu.state.depth_mask_set(False)
            shader=renderer.shader;shader.bind()
            for key,value in {'viewportSize':(512,512),'uiScale':1,'exposure':3,'thermalView':0,
                              'viewRight':(1,0,0),'viewUp':(0,0,1),'viewForward':(0,1,0)}.items():
                shader.uniform_float(key,value)
            shader.uniform_sampler('densityField',texture);shader.uniform_int('raySteps',128)
            samples=[]
            for i in range(25):
                start=perf_counter();renderer.batch.draw(shader)
                gpu.state.active_framebuffer_get().read_color(154,178,1,1,4,0,'FLOAT')
                if i>=5:samples.append((perf_counter()-start)*1000)
            return {'median_ms':median(samples),'samples_ms':samples,'method':'same 512x512 offscreen FluxFX renderer,128 ray samples,one-pixel synchronization; NOT native viewport FPS'}
    finally:
        gpu.state.blend_set(state[0]);gpu.state.depth_test_set(state[1]);gpu.state.depth_mask_set(state[2]);target.free()


def run_case(n,case,variant="baseline",out=None,settings_overrides=None,tag_prefix=None):
    output=Path(out) if out is not None else OUT
    native_output=OUT
    detail=variant!="baseline"
    calibrated=variant=="calibrated"
    curl=4.0 if variant in ("curl","calibrated") else 0.0
    rate=1.0 if calibrated else 5.2
    coupling=100.0 if calibrated else 20.0
    mode="TARGET" if calibrated else "RATE"
    profile="SOLID" if calibrated else "SOFT"
    transport="MACCORMACK" if detail else "SEMI_LAGRANGIAN"
    if variant not in ("baseline","detailed","curl","calibrated"):raise ValueError(variant)
    import bpy
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.timestep import AdaptiveTimestep
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.emission import Emission,Source
    from fluxfx.backend.diagnostics import collect
    output.mkdir(parents=True,exist_ok=True)
    tag=f'fluxfx-{case}-{n}' if variant=='baseline' else f'{variant}-{case}-{n}'
    if tag_prefix:tag=f'{tag_prefix}-{case}-{n}'
    report={'engine':'FluxFX','variant':variant,'case':case,'grid':n,'frames':60,'fps':30,'duration_seconds':2,
            'status':'RUNNING','frame_ms':[],'substeps_per_frame':[],'diagnostics':collect(False),
            'settings':{'domain_meters':1,'radius_meters':.09,'jet_mps':[0,0,.5],
                'density_value':rate,'density_mode':mode,'source_profile':profile,'scalar_advection':transport,'vorticity_strength':curl,'vorticity_limit':2,'velocity_coupling':coupling,'cfl':.75,'max_dt':1/30,
                'heat_buoyancy_decay':False,'closed_borders':True,'pressure_solver':'AUTO',
                'pressure_cycles':4,'pressure_iterations':80,'source_velocity_inheritance':0}}
    def save():(output/(tag+'.json')).write_text(json.dumps(report,indent=2))
    save()
    settings=PressureSettings(velocity=(0,0,0),angular_speed=0,source_center=positions(case,1)[0],
        pressure_warm_start="LEGACY",timestep_policy="QUANTIZED",coarse_solver="SMOOTH",pressure_cycles=4,pressure_solver="JACOBI" if n<128 else "MULTIGRID",source_radius=.09,source_rate=rate,density_mode=mode,source_profile=profile,scalar_advection=transport,vorticity_strength=curl,heat_source_rate=0,initial_temperature=0,
        thermal_lift=0,density_weight=0,dissipation=0,cooling=0)
    settings=replace(settings,**(settings_overrides or {}))
    report['solver_settings']=asdict(settings)
    report['settings'].update(asdict(settings))
    report['pressure_iterations_total']=0
    report['pressure_iterations_histogram']={}
    report['dt_changes']=0
    report['projection_samples']=[]
    previous_dt=None
    start=perf_counter();solver=DenseProjectedSmoke(GridSpec((n,)*3),settings);solver.reset(seed=False)
    controller=AdaptiveTimestep(solver.grid,solver.device);device=solver.device
    fence=device.kernel('benchmark_fence.glsl',samplers=('densityField','temperatureField','velocityU','velocityV','velocityW','divergenceField'))
    pixel=device.texture((1,1,1))
    def sync():
        device.dispatch(fence,pixel,(1,1,1),sources=dict(zip(
            ('densityField','temperatureField','velocityU','velocityV','velocityW','divergenceField'),
            (solver.density,solver.temperature,*solver._velocity,solver.projector.after))))
        assert math.isfinite(device.read(pixel,(1,1,1))[0])
    sync();report['setup_seconds']=perf_counter()-start
    previous=positions(case,1)
    try:
        for frame in range(1,61):
            target=frame/30;steps=0;start=perf_counter()
            while target-solver.time>1e-9:
                remaining=target-solver.time
                # Known jet targets establish adaptive bound before position sampling.
                hint=Emission(previous[0],(0,0,.5),coupling)
                dt=controller.select(solver,1/30,.75,hint)['dt']
                # Do not turn floating-point frame-boundary noise into cold pressure solves.
                if dt>remaining+1e-10:dt=remaining
                current=positions(case,(solver.time+dt)*30)
                records=[Source(c,.09,rate,0,Emission(p,(0,0,.5),coupling),mode,profile) for p,c in zip(previous,current)]
                if case=='multiple':solver.step(dt,sources=records)
                else:
                    solver.update_settings(replace(settings,source_center=current[0]))
                    solver.step(dt,records[0].motion)
                previous=current;steps+=1
                iterations=solver.projector.last_iterations
                report["pressure_iterations_total"]+=iterations
                histogram=report["pressure_iterations_histogram"];histogram[str(iterations)]=histogram.get(str(iterations),0)+1
                if previous_dt is not None and abs(previous_dt-dt)>1e-10:report["dt_changes"]+=1
                previous_dt=dt
            sync();report['frame_ms'].append((perf_counter()-start)*1000)
            report['substeps_per_frame'].append(steps)
            if frame%10==0:
                report["projection_samples"].append(solver.measure_projection())
                save()
        assert abs(solver.time-2)<1e-7
        density=array.array('f',solver.read_density())
        assert max(density)>0 and all(math.isfinite(v) for v in density)
        with gzip.open(output/(tag+'.f32.gz'),'wb') as f:f.write(density.tobytes())
        report['simulation_time']=solver.time;report['steps']=solver.steps
        report['simulation_evaluation_seconds']=sum(report['frame_ms'])/1000
        report['field_bytes']=solver.allocated_bytes+controller.allocated_bytes+4
        report['process_highwater_rss_bytes_NOT_comparable']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['projection']=solver.measure_projection()
        report['common_preview']=render_common(device,solver.density)
        # Upload native density outside timed rendering, then use identical display code.
        with gzip.open(native_output/f'mantaflow-{case}-{n}.f32.gz','rb') as f:
            native=array.array('f');native.frombytes(f.read())
        texture=device.texture((n,)*3,native)
        report['native_common_preview']=render_common(device,texture)
        report['status']='PASS'
    except Exception as exc:
        report['status']='FAIL';report['error']=repr(exc);raise
    finally:
        controller.close();solver.close();save()
    print('FLUXFX_COMPARISON',tag,report['status'],report['simulation_evaluation_seconds'])
    return report


def run_suite():
    import bpy,traceback
    from fluxfx.blender import runtime
    runtime.pause()
    cases=iter((n,case) for n in (64,128) for case in ('stationary','moving','multiple'))
    def tick():
        try:
            n,case=next(cases)
        except StopIteration:
            print('FLUXFX_COMPARISON_COMPLETE');return None
        try:run_case(n,case)
        except Exception:traceback.print_exc();return None
        return .2
    bpy.app.timers.register(tick,first_interval=.2)

if __name__=='__main__':run_suite()
