"""Three 64³ trials per configuration, plus one trial per 128³ release case."""
from pathlib import Path
import runpy
ROOT=Path(__file__).resolve().parents[1]
def run_suite():
    import bpy,traceback
    from fluxfx.blender import runtime
    runtime.pause()
    run_case=runpy.run_path(str(ROOT/'scripts/compare_fluxfx.py'))['run_case']
    cases=iter([(64,c,v,t) for t in range(1,4) for c in ('stationary','moving','multiple') for v in ('legacy','release')]+[(128,c,'release',1) for c in ('stationary','moving','multiple')])
    def tick():
        try:n,case,variant,trial=next(cases)
        except StopIteration:print('FLUXFX_RELEASE017_BENCHMARK_COMPLETE');return None
        changes={} if variant=='legacy' else {'pressure_warm_start':'AUTO','timestep_policy':'AUTO',
             'velocity_advection':'MACCORMACK','pressure_solver':'AUTO','pressure_cycles':2,'coarse_solver':'DIRECT'}
        try:
            result=run_case(n,case,'calibrated',ROOT/'test-results/release017',changes,f'{variant}-t{trial}')
            assert all(q['ratio']<.1 for q in result['projection_samples']),result['projection_samples']
        except Exception:traceback.print_exc();return None
        return .2
    bpy.app.timers.register(tick,first_interval=.2)
if __name__=='__main__':run_suite()
