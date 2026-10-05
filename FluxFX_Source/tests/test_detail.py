import unittest
from dataclasses import replace
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.interaction import validate_live_update
from fluxfx.physics.emission import Source,Emission,pack_sources

class DetailTests(unittest.TestCase):
    def test_live_settings(self):
        a=PressureSettings();b=replace(a,scalar_advection='MACCORMACK',vorticity_strength=4,vorticity_limit=2,density_mode='TARGET',source_profile='SOLID')
        validate_live_update(a,b)
    def test_invalid_settings(self):
        for change in ({'scalar_advection':'bogus'},{'vorticity_strength':-1},{'vorticity_strength':float('nan')},{'vorticity_limit':0},{'density_mode':'bogus'},{'source_profile':'bogus'}):
            with self.assertRaises(ValueError):replace(PressureSettings(),**change)
    def test_calibration_packing(self):
        data=pack_sources([Source((.5,)*3,.1,1,-10,Emission((.5,)*3),'TARGET','SOLID')])
        self.assertEqual(data[12:16],(-10,1,1,0))

    def test_motion_is_live(self):
        a=PressureSettings()
        validate_live_update(a,replace(a,velocity_advection='MACCORMACK'))

    def test_pressure_representation_requires_reset(self):
        a=PressureSettings()
        with self.assertRaises(ValueError):validate_live_update(a,replace(a,pressure_warm_start='LEGACY'))

    def test_invalid_motion_and_pressure_settings(self):
        for change in ({'velocity_advection':'bogus'},{'pressure_warm_start':'bogus'}):
            with self.assertRaises(ValueError):replace(PressureSettings(),**change)
