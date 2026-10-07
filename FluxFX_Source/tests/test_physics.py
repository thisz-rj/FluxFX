"""Independent numerical invariants; runs with ordinary Python, no Blender."""
from dataclasses import replace
import math
import unittest

from fluxfx.physics.config import GridSpec, AdvectionSettings, workgroups, validate_dt
from fluxfx.physics.reference import advect, sample_zero, source_weight, velocity_at


class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.grid = GridSpec((8, 6, 4))
        self.quiet = AdvectionSettings(velocity=(0, 0, 0), angular_speed=0, source_rate=0, dissipation=0)
        self.field = [float((i * 7) % 13) for i in range(8 * 6 * 4)]

    def test_zero_velocity_preserves_field(self):
        result = advect(self.field, self.grid, self.quiet, 0.05)
        self.assertLess(max(abs(a - b) for a, b in zip(result, self.field)), 1e-12)

    def test_exact_one_cell_translation(self):
        field = [0.0] * len(self.field)
        field[2 + 8 * (2 + 6 * 1)] = 1.0
        settings = replace(self.quiet, velocity=(1.25, 0, 0))
        moved = advect(field, self.grid, settings, 0.1)
        self.assertAlmostEqual(moved[3 + 8 * (2 + 6 * 1)], 1)
        self.assertAlmostEqual(sum(moved), 1)

    def test_half_cell_translation_splits_impulse(self):
        field = [0.0] * len(self.field)
        field[2 + 8 * (2 + 6 * 1)] = 1.0
        moved = advect(field, self.grid, replace(self.quiet, velocity=(0.625, 0, 0)), 0.1)
        self.assertAlmostEqual(moved[2 + 8 * (2 + 6 * 1)], 0.5)
        self.assertAlmostEqual(moved[3 + 8 * (2 + 6 * 1)], 0.5)

    def test_boundary_is_zero_extended_not_wrapped(self):
        field = [1.0] * len(self.field)
        self.assertAlmostEqual(sample_zero(field, self.grid.shape, (-0.5, 2, 1)), 0.5)
        self.assertEqual(sample_zero(field, self.grid.shape, (-2, 2, 1)), 0)
        moved = advect(field, self.grid, replace(self.quiet, velocity=(1.25, 0, 0)), 0.1)
        self.assertAlmostEqual(moved[0], 0)
        self.assertAlmostEqual(moved[1], 1)

    def test_decay_has_physical_time_units(self):
        s = replace(self.quiet, dissipation=0.7)
        result = advect(self.field, self.grid, s, 0.1)
        for actual, before in zip(result, self.field):
            self.assertAlmostEqual(actual, before * math.exp(-0.07))

    def test_source_integrates_rate(self):
        center = tuple(0.5 * h for h in self.grid.cell_size)
        s = replace(self.quiet, source_center=center, source_rate=4)
        self.assertEqual(source_weight(center, s), 1)
        result = advect([0.0] * len(self.field), self.grid, s, 0.05)
        self.assertAlmostEqual(result[0], 0.2)
        self.assertEqual(source_weight((10, 10, 10), s), 0)

    def test_constant_stays_constant_in_interior(self):
        s = replace(self.quiet, velocity=(0.1, -0.2, 0.3), angular_speed=0.6)
        result = advect([2.0] * len(self.field), self.grid, s, 0.05)
        self.assertAlmostEqual(result[3 + 8 * (3 + 6 * 2)], 2)

    def test_rotation_is_centered_in_physical_domain(self):
        s = replace(self.quiet, angular_speed=2)
        self.assertEqual(velocity_at((2, 3, 1), (4, 6, 2), s), (0, 0, 0))
        self.assertEqual(velocity_at((3, 3, 1), (4, 6, 2), s), (0, 2, 0))

    def test_positivity_and_no_new_extrema_without_sources(self):
        s = replace(self.quiet, velocity=(0.3, -0.2, 0.1), angular_speed=1)
        result = advect(self.field, self.grid, s, 0.07)
        self.assertGreaterEqual(min(result), 0)
        self.assertLessEqual(max(result), max(self.field))

    def test_invalid_parameters_rejected(self):
        for shape in ((0, 8, 8), (129, 8, 8), (8.0, 8, 8), (8, 8)):
            with self.assertRaises(ValueError):
                GridSpec(shape)
        for extent in ((1, 0, 1), (math.nan, 1, 1), (math.inf, 1, 1)):
            with self.assertRaises(ValueError):
                GridSpec(extent=extent)
        for dt in (0, -1, math.nan, math.inf, 0.2):
            with self.assertRaises(ValueError):
                validate_dt(dt)
        with self.assertRaises(ValueError):
            AdvectionSettings(source_rate=-1)
        with self.assertRaises(ValueError):
            AdvectionSettings(source_radius=0)
        with self.assertRaises(ValueError):
            AdvectionSettings(velocity=(0, math.nan, 0))

    def test_dispatch_roundup_and_memory_budget(self):
        self.assertEqual(workgroups((7, 5, 3)), (2, 2, 1))
        self.assertEqual(GridSpec().density_bytes, 2 * 1024 * 1024)
        self.assertEqual(GridSpec((128,) * 3).density_bytes, 16 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
