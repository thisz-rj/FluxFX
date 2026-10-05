import unittest
from dataclasses import replace
from math import sqrt
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.turbulence import spectrum
from fluxfx.physics.interaction import validate_live_update

class TurbulenceTests(unittest.TestCase):
    def test_transverse_bounded_spectrum(self):
        data=spectrum(GridSpec(),PressureSettings())
        bound=0
        for i in range(12):
            k=data[8*i:8*i+3];a=data[8*i+4:8*i+7]
            self.assertAlmostEqual(sum(x*y for x,y in zip(k,a)),0)
            bound+=sqrt(sum(v*v for v in a))
        self.assertLessEqual(bound,1.)
    def test_seed_and_reproducibility(self):
        g=GridSpec();s=PressureSettings()
        self.assertEqual(spectrum(g,s),spectrum(g,s))
        self.assertNotEqual(spectrum(g,s),spectrum(g,replace(s,turbulence_seed=1)))
    def test_unresolved_scales_zero(self):
        d=spectrum(GridSpec((16,)*3),PressureSettings(turbulence_scale=.1))
        self.assertTrue(all(d[8*i+j]==0 for i in range(12) for j in (4,5,6)))
    def test_live_update(self):
        a=PressureSettings();validate_live_update(a,replace(a,turbulence_strength=2,turbulence_seed=1))
    def test_invalid(self):
        for kw in ({'turbulence_strength':float('nan')},{'turbulence_scale':0},{'turbulence_mask':'FUEL'},
                   {'turbulence_seed':1.5},{'turbulence_octaves':5},{'turbulence_threshold':0}):
            with self.assertRaises(ValueError):PressureSettings(**kw)
