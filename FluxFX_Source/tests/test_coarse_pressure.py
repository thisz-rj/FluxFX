import unittest
from math import sin, fsum
from fluxfx.physics.coarse_pressure import coarse_inverse
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure_reference import laplacian

class CoarsePressureTests(unittest.TestCase):
    def test_inverse_matches_neumann_equation(self):
        for extent in ((1.,1.,1.),(1.3,.8,1.7)):
            grid=GridSpec((4,4,4),extent)
            rhs=[sin(i*.73) for i in range(64)]
            mean=fsum(rhs)/64;rhs=[v-mean for v in rhs]
            weights=coarse_inverse(extent)
            p=[fsum(weights[i*64+j]*rhs[j] for j in range(64)) for i in range(64)]
            self.assertLess(abs(fsum(p)),1e-12)
            self.assertLess(max(abs(a-b) for a,b in zip(laplacian(p,grid),rhs)),1e-12)
    def test_constant_mode_is_removed(self):
        weights=coarse_inverse((1.,1.,1.))
        self.assertLess(max(abs(fsum(weights[i*64:i*64+64])) for i in range(64)),1e-12)
