import unittest
from fluxfx.physics.emission import Emission,Source,pack_sources

class SourceTests(unittest.TestCase):
    def source(self):return Source((.2,.3,.4),.1,2,-30,Emission((.1,.3,.4),(1,2,3),10))
    def test_table_layout(self):
        data=pack_sources([self.source()])
        self.assertEqual(len(data),128)
        self.assertEqual(data[:16],(.2,.3,.4,.1,.1,.3,.4,10,1,2,3,2,-30,0,0,0))
        self.assertTrue(all(v==0 for v in data[16:]))
    def test_capacity(self):
        self.assertEqual(len(pack_sources([self.source()]*8)),128)
        with self.assertRaises(ValueError):pack_sources([self.source()]*9)
    def test_empty(self):self.assertTrue(all(v==0 for v in pack_sources([])))
    def test_invalid(self):
        for radius,density,heat in ((0,1,1),(.1,-1,1),(.1,1,float('nan'))):
            with self.assertRaises(ValueError):Source((.5,)*3,radius,density,heat,Emission((.5,)*3))
