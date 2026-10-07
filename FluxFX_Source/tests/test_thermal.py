from dataclasses import replace
from math import exp, prod, nan
import unittest
from fluxfx.physics.config import GridSpec
from fluxfx.physics.thermal import ThermalSettings, acceleration
from fluxfx.physics.mac_reference import advect_velocity, advect_density
from fluxfx.physics.thermal_reference import apply_buoyancy, step


class ThermalTests(unittest.TestCase):
    def setUp(self):
        self.grid = GridSpec((4, 3, 2))
        self.s = ThermalSettings(source_rate=0, heat_source_rate=0, dissipation=0, cooling=0)
        self.zero = tuple([0.] * prod(shape) for shape in self.grid.face_shapes)
        self.empty = [0.] * prod(self.grid.shape)

    def test_hot_cold_and_density_force_sign(self):
        self.assertGreater(acceleration(100, 0, self.s), 0)
        self.assertLess(acceleration(-100, 0, self.s), 0)
        self.assertLess(acceleration(0, 1, self.s), 0)
        self.assertEqual(acceleration(0, 0, self.s), 0)

    def test_equilibrium(self):
        self.assertAlmostEqual(acceleration(10, 1, self.s), 0)

    def test_only_vertical_faces_accelerate_in_seconds(self):
        result = apply_buoyancy(self.zero, self.empty, [100.] * 24, self.grid, self.s, .1)
        self.assertEqual(result[:2], self.zero[:2])
        for w in result[2]:
            self.assertAlmostEqual(w, .05)

    def test_face_average_and_boundary_extension(self):
        temperature = [0.] * 12 + [100.] * 12
        w = apply_buoyancy(self.zero, self.empty, temperature, self.grid, self.s, .1)[2]
        self.assertEqual(w[:12], [0.] * 12)
        self.assertEqual(w[12:24], [.025] * 12)
        self.assertEqual(w[24:], [.05] * 12)

    def test_signed_temperature_relaxes_to_ambient(self):
        s = replace(self.s, thermal_lift=0, density_weight=0, cooling=.7)
        field = [(-1) ** i * (i + 1) for i in range(24)]
        _, result, _ = step(self.empty, field, self.zero, self.grid, s, .1)
        for a, b in zip(result, field):
            self.assertAlmostEqual(a, b * exp(-.07))

    def test_heat_source_scales_with_time(self):
        center = tuple(.5 * x for x in self.grid.cell_size)
        s = replace(self.s, thermal_lift=0, density_weight=0, source_center=center, heat_source_rate=-40)
        _, temp, _ = step(self.empty, self.empty, self.zero, self.grid, s, .1)
        self.assertAlmostEqual(temp[0], -4.)

    def test_zero_force_matches_mac(self):
        s = replace(self.s, thermal_lift=0, density_weight=0)
        v = tuple([((i * 7) % 11 - 5) / 10 for i in range(prod(shape))] for shape in self.grid.face_shapes)
        density = [i / 24 for i in range(24)]
        new_v = advect_velocity(v, self.grid, .04)
        new_d = advect_density(density, new_v, self.grid, s, .04)
        result_d, _, result_v = step(density, self.empty, v, self.grid, s, .04)
        self.assertEqual(result_v, new_v)
        self.assertEqual(result_d, new_d)

    def test_thermal_parameters_rejected(self):
        for kwargs in ({'cooling':-1}, {'thermal_lift':-1}, {'density_weight':-1},
                       {'heat_source_rate':nan}, {'initial_temperature':nan}):
            with self.assertRaises(ValueError):
                ThermalSettings(**kwargs)
