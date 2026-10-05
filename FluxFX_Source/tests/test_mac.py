from dataclasses import replace
from math import prod
import unittest
from fluxfx.physics.config import GridSpec, AdvectionSettings
from fluxfx.physics.mac_reference import positions, seed_velocity, sample_velocity, advect_velocity, advect_density


class MACTests(unittest.TestCase):
    def setUp(self):
        self.grid = GridSpec((6, 5, 4), (2.0, 3.0, 4.0))
        self.settings = AdvectionSettings(velocity=(.2, -.3, .4), angular_speed=0, source_rate=0, dissipation=0)

    def test_face_shapes_and_memory(self):
        self.assertEqual(self.grid.face_shapes, ((7, 5, 4), (6, 6, 4), (6, 5, 5)))
        self.assertEqual(self.grid.mac_bytes, 8 * (120 + 140 + 144 + 150))

    def test_physical_face_positions(self):
        self.assertEqual(next(positions(self.grid, 0)), (0, .3, .5))
        self.assertEqual(next(positions(self.grid, 1)), (1 / 6, 0, .5))
        self.assertEqual(next(positions(self.grid, 2)), (1 / 6, .3, 0))
        self.assertEqual(list(positions(self.grid, 2))[-1][2], 4)

    def test_signed_constant_flow_including_boundary(self):
        fields = seed_velocity(self.grid, self.settings)
        for p in ((.7, 1.3, 2.2), (-10, 20, -1), (2, 3, 4)):
            for actual, expected in zip(sample_velocity(fields, self.grid, p), self.settings.velocity):
                self.assertAlmostEqual(actual, expected)
        new = advect_velocity(fields, self.grid, .1)
        for field, v in zip(new, self.settings.velocity):
            self.assertTrue(all(abs(x - v) < 1e-12 for x in field))

    def test_affine_staggered_reconstruction(self):
        fields = tuple([sum((i + 1) * a for i, a in enumerate(p)) + axis for p in positions(self.grid, axis)]
                       for axis in range(3))
        p = (.8, 1.4, 2.1)
        for axis, v in enumerate(sample_velocity(fields, self.grid, p)):
            self.assertAlmostEqual(v, .8 + 2 * 1.4 + 3 * 2.1 + axis)

    def test_shear_is_stationary(self):
        fields = ([p[1] - 1.5 for p in positions(self.grid, 0)],
                  [0.] * prod(self.grid.face_shapes[1]), [0.] * prod(self.grid.face_shapes[2]))
        advected = advect_velocity(fields, self.grid, .1)
        for before, after in zip(fields, advected):
            self.assertLess(max(abs(a - b) for a, b in zip(before, after)), 1e-12)

    def test_density_uses_stored_velocity(self):
        grid = GridSpec((8, 4, 4))
        fields = seed_velocity(grid, replace(self.settings, velocity=(1.25, 0, 0)))
        density = [0.] * 128
        density[2 + 8 * (1 + 4)] = 1.
        result = advect_density(density, fields, grid, self.settings, .1)
        self.assertAlmostEqual(result[3 + 8 * (1 + 4)], 1.)
        self.assertAlmostEqual(sum(result), 1.)

    def test_zero_fields_stay_zero(self):
        fields = tuple([0.] * prod(s) for s in self.grid.face_shapes)
        self.assertEqual(advect_velocity(fields, self.grid, .1), fields)

    def test_component_extrema_do_not_grow(self):
        fields = tuple([((i * 7) % 19 - 9) / 10 for i in range(prod(s))] for s in self.grid.face_shapes)
        result = advect_velocity(fields, self.grid, .07)
        for before, after in zip(fields, result):
            self.assertGreaterEqual(min(after), min(before) - 1e-12)
            self.assertLessEqual(max(after), max(before) + 1e-12)
