import unittest
from fluxfx.physics.emission import Emission, motion_velocity

class EmissionTests(unittest.TestCase):
    def test_motion_limit_preserves_direction(self):
        result=motion_velocity((0,0,0),(3,4,0),1,1,(0,0,1),2)
        for actual,expected in zip(result,(1.2,1.6,1.0)):self.assertAlmostEqual(actual,expected)
    def test_inheritance_off_keeps_jet(self):
        self.assertEqual(motion_velocity((0,0,0),(3,4,0),.01,0,(0,0,1),2),(0,0,1))
    def test_invalid_inputs(self):
        for args in (((0,0,0),(float('nan'),0,0),1),((0,0,0),(0,0,0),-1)):
            with self.assertRaises(ValueError):Emission(*args)
    def test_animation_time_units(self):
        self.assertEqual(motion_velocity((0,0,0),(.1,0,0),1/25,1,(0,0,0),10),(2.5,0,0))
