import math
import unittest
from fluxfx.physics.collision import Collider, primitive, raster_reference
from fluxfx.physics.config import GridSpec


class CollisionTests(unittest.TestCase):
    def test_sphere_and_box_boundaries(self):
        sphere=primitive('SPHERE',(.5,.5,.5),(.2,)*3)
        box=primitive('BOX',(.5,.5,.5),(.2,)*3)
        self.assertTrue(sphere.contains((.6,.5,.5)))
        self.assertFalse(sphere.contains((.69,.69,.5)))
        self.assertTrue(box.contains((.69,.69,.5)))
        self.assertFalse(box.contains((.71,.5,.5)))

    def test_affine_rotated_box(self):
        c=math.sqrt(.5)
        box=Collider('BOX',((c/.3,c/.3,0,0),(-c/.1,c/.1,0,0),(0,0,10,0)))
        self.assertTrue(box.contains((.2,.2,0)))
        self.assertFalse(box.contains((.2,-.2,0)))

    def test_union_and_non_cubic_grid(self):
        grid=GridSpec((8,6,4),(2,1,1))
        a=primitive('BOX',(.5,.5,.5),(.25,.2,.2))
        b=primitive('SPHERE',(1.5,.5,.5),(.25,.2,.2))
        ma=raster_reference(grid,(a,));mb=raster_reference(grid,(b,))
        self.assertEqual(raster_reference(grid,(a,b)),[max(x,y) for x,y in zip(ma,mb)])
        self.assertGreater(sum(ma),0)

    def test_invalid_geometry(self):
        for args in [('MESH',((1,0,0,0),(0,1,0,0),(0,0,1,0))),
                     ('BOX',((0,0,0,0),)*3),('BOX',((float('nan'),0,0,0),)*3)]:
            with self.assertRaises(ValueError):Collider(*args)
        with self.assertRaises(ValueError):primitive('BOX',(0,0,0),(1,0,1))
