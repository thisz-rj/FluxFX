"""Matched-input projection comparison and coupled multigrid smoke checks."""
from pathlib import Path
from time import perf_counter
from math import cos,pi,prod,isfinite
from statistics import median
import json
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    from fluxfx.backend.device import BlenderGPUDevice
    from fluxfx.backend.pressure import PressureProjector
    from fluxfx.backend.multigrid import MultigridPressureProjector
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.thermal import DenseThermalAdvection
    from fluxfx.backend.timestep import AdaptiveTimestep
    from fluxfx.backend.diagnostics import collect
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure_reference import cells,pressure_gradient,divergence,walls
    report={'status':'RUNNING','diagnostics':collect(True),'tests':[],'comparisons':[]}
    output=ROOT/'test-results/multigrid-validation.json'
    def save():output.write_text(json.dumps(report,indent=2)+'\n')
    device=BlenderGPUDevice()
    for shape in ((8,8,8),(16,8,8),(9,7,5)):
        grid=GridSpec(shape,(1.3,.8,1.7))
        p=[cos(pi*(x+.5)/shape[0])+.2*cos(pi*(z+.5)/shape[2]) for x,y,z in cells(shape)]
        velocity=pressure_gradient(p,grid)
        fields=[device.texture(s,v,nonnegative=False) for s,v in zip(grid.face_shapes,velocity)]
        outputs=[device.texture(s) for s in grid.face_shapes]
        mg=MultigridPressureProjector(grid,device=device)
        try:
            mg.project(fields,outputs,.04)
            result=tuple(device.read(f,s) for f,s in zip(outputs,grid.face_shapes))
            metrics=mg.metrics()
            assert result==walls(result,grid)
            assert all(isfinite(v) for component in result for v in component)
            assert metrics['ratio']<.05,(shape,metrics)
            report['tests'].append({'name':'manufactured_gradient','shape':shape,**metrics})
        finally:mg.close()
    save()
    for n in (64,128):
        grid=GridSpec((n,n,n))
        source=DenseThermalAdvection(grid)
        for _ in range(20):source.step(1/30)
        outputs=[device.texture(s) for s in grid.face_shapes]
        # Single-texel fence depends on corrected outputs and divergence.
        fence=device.kernel('benchmark_fence.glsl',samplers=('densityField','temperatureField','velocityU','velocityV','velocityW','divergenceField'))
        pixel=device.texture((1,1,1))
        def sync(projector):
            device.dispatch(fence,pixel,(1,1,1),sources=dict(zip(
                ('densityField','temperatureField','velocityU','velocityV','velocityW','divergenceField'),
                (source.density,source.temperature,*outputs,projector.after))))
            device.read(pixel,(1,1,1))
        comparison={'grid':n}
        for name,cls in (('jacobi',PressureProjector),('multigrid',MultigridPressureProjector)):
            solver=cls(grid,device=device)
            try:
                sync(solver)
                start=perf_counter();solver.project(source._velocity,outputs,1/30);sync(solver)
                cold=(perf_counter()-start)*1000
                first=solver.metrics()
                timings=[]
                for _ in range(10):
                    start=perf_counter();solver.project(source._velocity,outputs,1/30);sync(solver)
                    timings.append((perf_counter()-start)*1000)
                comparison[name]={'cold_ms':cold,'median_ms':median(timings),'samples_ms':timings,'first':first,'last':solver.metrics()}
            finally:solver.close()
        source.close()
        assert comparison['multigrid']['first']['ratio'] < comparison['jacobi']['first']['ratio']
        assert comparison['multigrid']['last']['ratio'] < comparison['jacobi']['last']['ratio']
        report['comparisons'].append(comparison);save()
        for adaptive in (False,True):
            solver=DenseProjectedSmoke(grid,projector_class=MultigridPressureProjector)
            control=AdaptiveTimestep(grid,solver.device)
            try:
                first=None
                for _ in range(30):
                    dt=control.select(solver,1/30,.75)['dt'] if adaptive else 1/30
                    solver.step(dt)
                    if first is None:first=solver.measure_projection()
                last=solver.measure_projection()
                assert first['ratio']<.1 and last['ratio']<.1,(n,adaptive,first,last)
                report['tests'].append({'name':'coupled','grid':n,'adaptive':adaptive,'first':first,'last':last})
            finally:control.close();solver.close()
        save()
    report['status']='PASS';save();print('FLUXFX_MULTIGRID_PASS',report['comparisons'])
    return report

if __name__=='__main__':run_suite()
