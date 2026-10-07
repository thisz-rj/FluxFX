from dataclasses import replace
import unittest
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.interaction import validate_live_update, reset_signature, LIVE_FIELDS


class InteractionTests(unittest.TestCase):
    def test_live_fields_preserve_signature(self):
        a = PressureSettings()
        b = replace(a, source_center=(.2,.3,.4), source_radius=.2, source_rate=0,
                    heat_source_rate=-10, cooling=1, dissipation=.2,
                    thermal_lift=.01, density_weight=.1, pressure_iterations=120)
        validate_live_update(a,b)
        self.assertEqual(reset_signature(a),reset_signature(b))

    def test_initial_changes_require_reset(self):
        a=PressureSettings()
        for change in ({'velocity':(0,0,1)}, {'angular_speed':1}, {'initial_temperature':20},
                       {'pressure_relaxation':.5}, {'pressure_cold_multiplier':2}):
            with self.assertRaises(ValueError):
                validate_live_update(a,replace(a,**change))

    def test_invalid_live_settings_rejected(self):
        for change in ({'source_radius':0}, {'source_rate':-1}, {'cooling':-1},
                       {'source_center':(float('nan'),0,0)}, {'pressure_iterations':0}):
            with self.assertRaises(ValueError):
                replace(PressureSettings(),**change)
