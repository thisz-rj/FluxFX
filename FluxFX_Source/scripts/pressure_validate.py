"""P0.5 GPU projection/coupling suite; run_suite() needs a Blender window."""
from dataclasses import replace
from math import cos, pi, prod, isfinite
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_suite():
    from fluxfx.backend.diagnostics import collect
    from fluxfx.backend.device import BlenderGPUDevice
    from fluxfx.backend.pressure import PressureProjector
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.pressure_reference import project, cells, pressure_gradient, walls, divergence, laplacian
    report = {'diagnostics': collect(True), 'tests': []}
    assert report['diagnostics']['status'] == 'READY'
    device = BlenderGPUDevice()
    grid = GridSpec((9, 7, 5), (1.3, .8, 1.7))
    random_velocity = tuple([((i * 7 + axis * 3) % 19 - 9) / 13 for i in range(prod(s))]
                            for axis, s in enumerate(grid.face_shapes))
    pressure_mode = [cos(pi * (x + .5) / grid.shape[0]) for x,y,z in cells(grid.shape)]
    for name, values, iterations in (
        ('random_noncubic', random_velocity, 160),
        ('manufactured_gradient', pressure_gradient(pressure_mode, grid), 1000),
        ('zero', tuple([0.] * prod(s) for s in grid.face_shapes), 80)):
        settings = PressureSettings(pressure_iterations=iterations, pressure_cold_multiplier=1)
        projector = PressureProjector(grid, settings, device)
        fields = [device.texture(s, v, nonnegative=False) for s,v in zip(grid.face_shapes, values)]
        output = [device.texture(s) for s in grid.face_shapes]
        try:
            expected, expected_p, expected_metrics = project(values, grid, .04, iterations)
            projector.project(fields, output, .04)
            actual = tuple(device.read(t,s) for t,s in zip(output,grid.face_shapes))
            metrics = projector.metrics()
            error = max(abs(a-b) for aa,bb in zip(actual,expected) for a,b in zip(aa,bb))
            pressure = [v/(.04 if projector.uses_impulse else 1.) for v in device.read(projector.pressure,grid.shape)]
            error_p = max(abs(a-b) for a,b in zip(pressure,expected_p))
            assert error < 5e-5 and error_p < 2e-4,(name,error,error_p)
            assert actual == walls(actual,grid),name
            assert all(isfinite(v) for f in actual for v in f)
            if name != 'zero':
                assert metrics['ratio'] < .01,(name,metrics)
            else:
                assert not any(v for f in actual for v in f) and metrics['ratio'] == 0
            # Independent divergence verifies GPU diagnostics, including face indexing.
            cpu_div = divergence(actual,grid)
            gpu_div = device.read(projector.after,grid.shape)
            assert max(abs(a-b) for a,b in zip(cpu_div,gpu_div)) < 2e-5
            bounded_div = divergence(walls(values,grid),grid)
            lp = laplacian(pressure,grid)
            identity_error = max(abs(a-(b-.04*l)) for a,b,l in zip(cpu_div,bounded_div,lp))
            assert identity_error < 5e-5
            report['tests'].append({'name':name,'status':'PASS','velocity_error':error,
                'pressure_error':error_p,'residual_identity_error':identity_error,**metrics})
        finally:
            projector.close()
            fields = output = None
    # Scalars must use closed extension, and reset must invalidate diagnostics.
    params = PressureSettings(source_rate=0, heat_source_rate=0, cooling=0, dissipation=0,
                              thermal_lift=0, density_weight=0)
    solver = DenseProjectedSmoke(grid, params)
    try:
        solver.upload([2.] * prod(grid.shape))
        solver.upload_temperature([-10.] * prod(grid.shape))
        solver.upload_velocity(random_velocity)
        solver.step(.04)
        assert max(abs(v-2.) for v in solver.read_density()) < 2e-5
        assert max(abs(v+10.) for v in solver.read_temperature()) < 5e-5
        solver.reset()
        assert not solver.projector.ready
        try:
            solver.measure_projection()
            raise AssertionError('Reset left stale diagnostics available')
        except RuntimeError:
            pass
        solver.reset(seed=False)
        assert not any(solver.read_density()) and not any(solver.read_temperature())
        report['tests'].append({'name':'closed_scalar_constants_and_reset','status':'PASS'})
    finally:
        solver.close()
    for n, steps in ((64,30),(128,10)):
        solver = DenseProjectedSmoke(GridSpec((n,)*3))
        try:
            first = None
            for i in range(steps):
                solver.step()
                if i == 0:
                    first = solver.measure_projection()
            metrics = solver.measure_projection()
            d = solver.read_density(); t = solver.read_temperature(); velocity = solver.read_velocity()
            assert all(isfinite(v) and v >= 0 for v in d)
            assert all(isfinite(v) for v in t)
            assert all(isfinite(v) for f in velocity for v in f)
            assert velocity == walls(velocity,solver.grid)
            assert first['ratio'] < .1 and metrics['ratio'] < .1,(n,first,metrics)
            assert max(velocity[2]) > 0 and min(velocity[2]) < 0
            report['tests'].append({'name':f'projected_{n}_{steps}_steps','status':'PASS',
                'field_bytes':solver.allocated_bytes,'first_projection':first,'last_projection':metrics,
                'max_vertical_speed':max(velocity[2]),'min_vertical_speed':min(velocity[2])})
            del d,t,velocity
        finally:
            solver.close()
    report['status'] = 'PASS'
    return report
