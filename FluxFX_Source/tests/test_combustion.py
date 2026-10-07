import unittest
from dataclasses import replace
from math import exp
from fluxfx.physics.combustion import react
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.interaction import validate_live_update
from fluxfx.physics.emission import Source, Emission, pack_sources
from fluxfx.physics.playback import source_span

class CombustionTests(unittest.TestCase):
    def test_ignition_and_exhaustion(self):
        self.assertEqual(react(1,149,.1,150,4),0)
        self.assertEqual(react(0,200,.1,150,4),0)
        self.assertEqual(react(1,200,.1,150,0),0)
        self.assertAlmostEqual(react(1,150,.1,150,4),1-exp(-.4))
    def test_subdivision_invariance(self):
        f=1.
        for _ in range(10):f-=react(f,200,.01,150,4)
        self.assertAlmostEqual(f,1-react(1,200,.1,150,4))
    def test_nonnegative_fuel(self):
        for k in (0,4,10000):self.assertTrue(0<=react(1,200,.1,150,k)<=1)
    def test_invalid_settings(self):
        for key in ('fuel_source_rate','ignition_temperature','burn_rate','heat_yield','smoke_yield'):
            for value in (-1,float('nan'),float('inf')):
                with self.assertRaises(ValueError):PressureSettings(**{key:value})
    def test_live_rates_reset_mode(self):
        s=PressureSettings();validate_live_update(s,replace(s,burn_rate=2))
        with self.assertRaises(ValueError):validate_live_update(s,replace(s,combustion_enabled=True))
    def test_fuel_table_and_sweep(self):
        s=Source((.5,)*3,.1,0,0,Emission((.2,)*3),fuel_rate=3)
        self.assertEqual(pack_sources([s])[15],3)
        self.assertEqual(source_span(s,0,.5).fuel_rate,3)
        with self.assertRaises(ValueError):replace(s,fuel_rate=-1)
