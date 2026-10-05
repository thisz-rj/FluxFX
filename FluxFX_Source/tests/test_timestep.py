import unittest
from fluxfx.physics.timestep import choose_timestep

class TimestepTests(unittest.TestCase):
    def test_rest(self): self.assertEqual(choose_timestep(.03,.75,0),.03)
    def test_fast_flow(self):
        dt=choose_timestep(.03,.75,100)
        self.assertEqual(dt,.0075)
        self.assertLessEqual(dt*100,.75)
    def test_acceleration_from_rest(self):
        dt=choose_timestep(.1,.75,0,10000)
        self.assertLessEqual(dt*dt*10000,.75)
        self.assertGreater((2*dt)**2*10000,.75)
    def test_combined(self):
        for rate in (0,1,100,1000):
            for acc in (0,1,100,10000):
                dt=choose_timestep(.1,.75,rate,acc)
                self.assertLessEqual(rate*dt+acc*dt*dt,.75)
    def test_invalid(self):
        for args in ((0,.75,0),(.03,0,0),(.03,.75,-1),(.03,.75,float('nan'))):
            with self.assertRaises(ValueError): choose_timestep(*args)
    def test_extreme_stops(self):
        with self.assertRaises(RuntimeError): choose_timestep(.03,.75,1e9)

    def test_continuous_policy_uses_bound_without_overshoot(self):
        for rate in (0,1,100,1000):
            for acc in (0,1,100,10000):
                dt=choose_timestep(.1,.75,rate,acc,quantized=False)
                self.assertLessEqual(rate*dt+acc*dt*dt,.75)
                self.assertLessEqual(dt,.1)
                self.assertGreaterEqual(dt,choose_timestep(.1,.75,rate,acc)*.99)

    def test_continuous_policy_rejects_extreme_flow(self):
        with self.assertRaises(RuntimeError):choose_timestep(.03,.75,1e9,quantized=False)
