from math import cos, pi, prod, fsum, sqrt
import unittest
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings, divergence_stats
from fluxfx.physics.pressure_reference import cells, walls, divergence, laplacian, pressure_gradient, project


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.grid = GridSpec((6, 5, 4), (1.3, .8, 1.7))
        self.velocity = tuple([((i * 7 + axis * 3) % 19 - 9) / 13 for i in range(prod(s))]
                              for axis, s in enumerate(self.grid.face_shapes))

    def test_all_six_walls_zero_without_changing_interior(self):
        bounded = walls(self.velocity, self.grid)
        for axis, (field, original, shape) in enumerate(zip(bounded, self.velocity, self.grid.face_shapes)):
            for c, value, old in zip(cells(shape), field, original):
                self.assertEqual(value, 0 if c[axis] in (0, shape[axis] - 1) else old)

    def test_closed_divergence_compatibility(self):
        div = divergence(walls(self.velocity, self.grid), self.grid)
        self.assertAlmostEqual(fsum(div), 0, places=12)

    def test_divergence_of_gradient_equals_neumann_laplacian(self):
        p = [((i * 11) % 17) / 17 for i in range(prod(self.grid.shape))]
        dg = divergence(pressure_gradient(p, self.grid), self.grid)
        lp = laplacian(p, self.grid)
        self.assertLess(max(abs(a - b) for a, b in zip(dg, lp)), 1e-12)

    def test_manufactured_pressure_mode_removed(self):
        pressure = [cos(pi * (x + .5) / self.grid.shape[0]) for x, y, z in cells(self.grid.shape)]
        field = pressure_gradient(pressure, self.grid)
        result, _, metrics = project(field, self.grid, .04, iterations=500)
        self.assertLess(metrics['ratio'], 1e-4)
        self.assertLess(max(abs(v) for f in result for v in f), 1e-3)

    def test_random_field_strong_reduction(self):
        result, _, metrics = project(self.velocity, self.grid, .04, iterations=160)
        self.assertLess(metrics['ratio'], .01)
        self.assertEqual(result, walls(result, self.grid))

    def test_zero_field_stays_zero(self):
        zero = tuple([0.] * prod(s) for s in self.grid.face_shapes)
        result, pressure, metrics = project(zero, self.grid, .1)
        self.assertEqual(result, zero)
        self.assertFalse(any(pressure))
        self.assertEqual(metrics['ratio'], 0)

    def test_projection_independent_of_dt_for_fixed_input(self):
        a, pa, _ = project(self.velocity, self.grid, .04)
        b, pb, _ = project(self.velocity, self.grid, .02)
        self.assertLess(max(abs(x-y) for aa, bb in zip(a,b) for x,y in zip(aa,bb)), 1e-12)
        self.assertLess(max(abs(x-2*y) for x,y in zip(pb,pa)), 1e-12)

    def test_pressure_constant_gauge_does_not_change_gradient(self):
        p = [i / 10 for i in range(prod(self.grid.shape))]
        a = pressure_gradient(p, self.grid)
        b = pressure_gradient([v+17 for v in p], self.grid)
        self.assertLess(max(abs(x-y) for aa,bb in zip(a,b) for x,y in zip(aa,bb)), 1e-12)

    def test_pressure_residual_equals_remaining_divergence(self):
        result, pressure, _ = project(self.velocity, self.grid, .04, iterations=37)
        before = divergence(walls(self.velocity, self.grid), self.grid)
        after = divergence(result, self.grid)
        lp = laplacian(pressure, self.grid)
        self.assertLess(max(abs(a-(b-.04*l)) for a,b,l in zip(after,before,lp)), 1e-12)

    def test_more_iterations_improve_residual(self):
        _, _, a = project(self.velocity, self.grid, .04, iterations=20)
        _, _, b = project(self.velocity, self.grid, .04, iterations=80)
        self.assertLess(b['rms_after'], a['rms_after'])

    def test_projection_does_not_add_kinetic_energy(self):
        bounded = walls(self.velocity, self.grid)
        result, _, _ = project(self.velocity, self.grid, .04, iterations=160)
        self.assertLessEqual(fsum(v*v for f in result for v in f), fsum(v*v for f in bounded for v in f))

    def test_settings_and_metrics_validation(self):
        for kwargs in ({'pressure_iterations':0}, {'pressure_iterations':1.5}, {'pressure_iterations':True},
                       {'pressure_relaxation':1}, {'pressure_relaxation':float('nan')}):
            with self.assertRaises(ValueError):
                PressureSettings(**kwargs)
        with self.assertRaises(ValueError):
            divergence_stats([1], [float('nan')])
