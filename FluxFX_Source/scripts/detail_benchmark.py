"""GUI quality suite. Preserves 0.15 outputs and reuses its native reference arrays."""
from pathlib import Path
import runpy
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    import bpy,traceback
    from fluxfx.blender import runtime
    runtime.pause()
    run_case=runpy.run_path(str(ROOT/'scripts/compare_fluxfx.py'))['run_case']
    cases=iter([(64,'stationary',v) for v in ('baseline','detailed','curl')]+[(n,c,'calibrated') for n in (64,128) for c in ('stationary','moving','multiple')])
    def tick():
        try:n,case,variant=next(cases)
        except StopIteration:print('FLUXFX_DETAIL_BENCHMARK_COMPLETE');return None
        try:run_case(n,case,variant,ROOT/'test-results/detail-comparison')
        except Exception:traceback.print_exc();return None
        return .2
    bpy.app.timers.register(tick,first_interval=.2)

if __name__=='__main__':run_suite()
