from dataclasses import replace
import unittest
from fluxfx.backend.multigrid import hierarchy_shapes, use_multigrid
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.interaction import validate_live_update


class MultigridSettingsTests(unittest.TestCase):
    def test_hierarchy_covers_same_domain(self):
        levels=hierarchy_shapes((128,64,32))
        self.assertEqual(levels,[(128,64,32),(64,32,16),(32,16,8),(16,8,4)])
        self.assertEqual(hierarchy_shapes((9,7,5)),[(9,7,5)])
    def test_auto_uses_coarsenable_supported_grids(self):
        self.assertTrue(use_multigrid(GridSpec(),PressureSettings()))
        self.assertTrue(use_multigrid(GridSpec((128,128,128)),PressureSettings()))
        self.assertFalse(use_multigrid(GridSpec((128,127,128)),PressureSettings()))
    def test_manual_choice(self):
        self.assertTrue(use_multigrid(GridSpec(),PressureSettings(pressure_solver='MULTIGRID')))
        self.assertFalse(use_multigrid(GridSpec((128,128,128)),PressureSettings(pressure_solver='JACOBI')))
    def test_cycles_live_but_solver_requires_reset(self):
        settings=PressureSettings()
        validate_live_update(settings,replace(settings,pressure_cycles=8))
        with self.assertRaises(ValueError): validate_live_update(settings,replace(settings,pressure_solver='MULTIGRID'))
    def test_invalid_budget(self):
        for cycles in (0,17,1.5,True):
            with self.assertRaises(ValueError): PressureSettings(pressure_cycles=cycles)
        with self.assertRaises(ValueError): PressureSettings(pressure_solver='bad')
