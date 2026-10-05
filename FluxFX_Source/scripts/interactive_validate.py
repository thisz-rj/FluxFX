"""P0.6 actual GPU live-emission invariants, graphical Blender only."""
from dataclasses import replace
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def run_suite():
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.diagnostics import collect
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.config import GridSpec
    report={'diagnostics':collect(True),'tests':[]}
    assert report['diagnostics']['status']=='READY'
    settings=PressureSettings(pressure_solver="JACOBI",source_center=(.25,.5,.5),source_radius=.18,
        source_rate=2,heat_source_rate=30,thermal_lift=0,density_weight=0,
        dissipation=0,cooling=0,initial_temperature=0)
    grid=GridSpec((16,16,16))
    solver=DenseProjectedSmoke(grid,settings)
    def record(name): report['tests'].append({'name':name,'status':'PASS'})
    try:
        solver.reset(seed=False)
        solver.step(.04)
        density=solver.read_density(); heat=solver.read_temperature()
        assert max(density)>0 and max(heat)>0
        record('emission_from_empty')
        fields=(solver.density,solver.temperature,*solver._velocity,solver.projector.pressure)
        off=replace(settings,source_rate=0,heat_source_rate=0)
        solver.update_settings(off)
        assert fields==(solver.density,solver.temperature,*solver._velocity,solver.projector.pressure)
        assert solver.steps==1 and solver.projector.last_dt==.04
        solver.step(.04)
        assert max(abs(a-b) for a,b in zip(density,solver.read_density()))<1e-6
        assert max(abs(a-b) for a,b in zip(heat,solver.read_temperature()))<1e-5
        record('emission_off_preserves_existing_scalars_and_fields')
        moved=replace(settings,source_center=(.75,.5,.5),source_radius=.15)
        solver.update_settings(moved)
        solver.step(.04)
        after=solver.read_density(); after_heat=solver.read_temperature()
        err=0
        for i,(a,b) in enumerate(zip(after,density)):
            x=i%16; y=(i//16)%16; z=i//256
            distance=sum(((v+.5)/16-c)**2 for v,c in zip((x,y,z),moved.source_center))
            w=max(1-distance/moved.source_radius**2,0)**2
            err=max(err,abs(a-b-.04*moved.source_rate*w))
            assert abs(after_heat[i]-heat[i]-.04*moved.heat_source_rate*w)<1e-5
        assert err<1e-6 and solver.steps==3
        record('moved_resized_source_matches_analytic_injection')
        solver.update_settings(replace(moved,pressure_iterations=12))
        solver.step(.04)
        assert solver.projector.last_iterations==12 and solver.steps==4
        record('live_pressure_budget')
        prior=solver.settings
        try:
            solver.update_settings(replace(prior,initial_temperature=200))
            raise AssertionError('initial state accepted')
        except ValueError:
            assert solver.settings==prior and solver.steps==4
        record('initial_state_change_rejected_without_mutation')
        report['status']='PASS'
    finally:
        solver.close()
    output=ROOT/'test-results/interactive-validation.json'
    output.write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_INTERACTIVE',report)
    return report


if __name__=='__main__':
    run_suite()
