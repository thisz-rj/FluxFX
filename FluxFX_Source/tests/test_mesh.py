import unittest
from dataclasses import replace
from fluxfx.physics.mesh import MeshCollider,validate_mesh

V=((0.,0.,0.),(1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
T=((0,2,1),(0,1,3),(1,2,3),(2,0,3))
class MeshTests(unittest.TestCase):
    def test_closed_tetrahedron_and_reversed_winding(self):
        self.assertEqual(validate_mesh(MeshCollider(V,T)),4)
        self.assertEqual(validate_mesh(MeshCollider(V,tuple(tuple(reversed(t)) for t in T))),4)
    def test_open_surface(self):
        with self.assertRaisesRegex(ValueError,'closed'):validate_mesh(MeshCollider(V,T[:-1]))
    def test_inconsistent_winding(self):
        with self.assertRaisesRegex(ValueError,'winding'):validate_mesh(MeshCollider(V,(tuple(reversed(T[0])),)+T[1:]))
    def test_degenerate_triangle(self):
        with self.assertRaises(ValueError):validate_mesh(MeshCollider(V,((0,0,1),)))
    def test_nonfinite_geometry(self):
        with self.assertRaises(ValueError):validate_mesh(MeshCollider(((float('nan'),0,0),)+V[1:],T))
    def test_disconnected_shells(self):
        shifted=tuple(tuple(c+2 for c in v) for v in V)
        with self.assertRaisesRegex(ValueError,'connected'):validate_mesh(MeshCollider(V+shifted,T+tuple(tuple(i+4 for i in t) for t in T)))
