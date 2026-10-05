"""P0.3 GPU suite. Run run_suite() in a graphical Blender context."""
from dataclasses import replace
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_suite():
    from fluxfx.backend.mac import DenseMACAdvection
    from fluxfx.physics.config import GridSpec, AdvectionSettings
    from fluxfx.physics.mac_reference import seed_velocity, advect_velocity, advect_density, positions
    from fluxfx.backend.diagnostics import collect
    report = {'diagnostics': collect(True), 'tests': []}
    assert report['diagnostics']['status'] == 'READY'
    grid = GridSpec((7, 5, 3), (1.3, 1.1, .9))
    settings = AdvectionSettings(velocity=(.17, -.21, .13), angular_speed=.7, source_radius=.3)
    initial = [((i * 11) % 23) / 23 for i in range(math.prod(grid.shape))]
    for name in ('zero', 'constant', 'shear', 'signed_nonuniform'):
        params = replace(settings, angular_speed=0) if name == 'constant' else settings
        solver = DenseMACAdvection(grid, params)
        try:
            fields = seed_velocity(grid, params)
            seed = solver.read_velocity()
            seed_error = max(abs(a - b) for aa, bb in zip(seed, fields) for a, b in zip(aa, bb))
            assert seed_error < 2e-6, seed_error
            if name == 'zero':
                fields = tuple([0.] * math.prod(s) for s in grid.face_shapes)
            elif name == 'shear':
                fields = ([p[1] - .5 for p in positions(grid, 0)],
                          [0.] * math.prod(grid.face_shapes[1]), [0.] * math.prod(grid.face_shapes[2]))
            elif name == 'signed_nonuniform':
                fields = tuple([((i * 7 + axis * 3) % 19 - 9) / 13 for i in range(math.prod(s))]
                               for axis, s in enumerate(grid.face_shapes))
            solver.upload(initial)
            solver.upload_velocity(fields)
            density = initial
            for _ in range(4):
                fields = advect_velocity(fields, grid, .04)
                density = advect_density(density, fields, grid, params, .04)
                solver.step(.04)
            actual = solver.read_velocity()
            err_v = max(abs(a - b) for aa, bb in zip(actual, fields) for a, b in zip(aa, bb))
            err_d = max(abs(a - b) for a, b in zip(solver.read_density(), density))
            assert all(math.isfinite(v) for f in actual for v in f)
            assert err_v < 2e-5 and err_d < 2e-5, (name, err_v, err_d)
            solver.reset()
            assert solver.read_velocity() == seed
            report['tests'].append({'name':name, 'status':'PASS', 'steps':4,
                                    'velocity_error':err_v, 'density_error':err_d, 'seed_error':seed_error})
        finally:
            solver.close()
    for n in (64, 128):
        solver = DenseMACAdvection(GridSpec((n,) * 3))
        try:
            for _ in range(30):
                solver.step()
            field = solver.read_density()
            assert all(math.isfinite(v) and v >= 0 for v in field) and max(field) > 0
            velocity = solver.read_velocity()
            assert all(math.isfinite(v) for component in velocity for v in component)
            report['tests'].append({'name':f'mac_{n}_30_steps', 'status':'PASS',
                                    'field_bytes':solver.allocated_bytes,
                                    'velocity_min':[min(f) for f in velocity],
                                    'velocity_max':[max(f) for f in velocity]})
            del velocity, field
        finally:
            solver.close()
    report['status'] = 'PASS'
    return report
