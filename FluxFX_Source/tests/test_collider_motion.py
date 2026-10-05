import unittest,math
from fluxfx.physics.collision import primitive,Collider
from fluxfx.physics.collider_motion import Pose,MotionPath,velocity_rows


class ColliderMotionTests(unittest.TestCase):
    def test_roundtrip_rotated_box(self):
        p=Pose('BOX',(.3,.4,.5),(.1,.2,.3),(math.cos(.7),0,0,math.sin(.7)))
        recovered=Pose.from_collider(p.collider())
        for a,b in zip(recovered.center,p.center):self.assertAlmostEqual(a,b)
        for a,b in zip(recovered.size,p.size):self.assertAlmostEqual(a,b)
        for a,b in zip(recovered.collider().inverse_rows,p.collider().inverse_rows):
            for x,y in zip(a,b):self.assertAlmostEqual(x,y)

    def test_motion_cap_and_substeps(self):
        a=primitive('SPHERE',(.1,.5,.5),(.1,)*3);b=primitive('SPHERE',(.9,.5,.5),(.1,)*3)
        path=MotionPath((a,),(b,),.01)
        self.assertAlmostEqual(path.speed,2)
        dt=path.limit_dt(1/30,(1/64,)*3)
        self.assertLessEqual(path.speed*dt,.5/64)
        c=Pose.from_collider(path.at(dt)[0]);self.assertAlmostEqual(c.center[0],.1+2*dt)

    def test_rotation_preserves_size(self):
        a=Pose('BOX',(.5,)*3,(.1,.2,.3),(1.,0,0,0))
        b=Pose('BOX',(.5,)*3,(.1,.2,.3),(0.,0,0,1.))
        path=MotionPath((a.collider(),),(b.collider(),),1.)
        mid=Pose.from_collider(path.at(path.duration/2)[0])
        for x,y in zip(mid.size,a.size):self.assertAlmostEqual(x,y)
        rows=velocity_rows(a.collider(),mid.collider(),1.)
        self.assertAlmostEqual(rows[0][1],-math.pi/2)
        self.assertAlmostEqual(rows[1][0],math.pi/2)

    def test_size_shape_shear_changes_rejected(self):
        a=primitive('SPHERE',(.5,)*3,(.1,)*3)
        for b in (primitive('BOX',(.5,)*3,(.1,)*3),primitive('SPHERE',(.5,)*3,(.2,)*3),Collider('SPHERE',((10,1,0,0),(0,10,0,0),(0,0,10,0)))):
            with self.assertRaises(ValueError):MotionPath((a,),(b,),.1)

    def test_rest_has_zero_wall_velocity(self):
        a=primitive('BOX',(.5,)*3,(.1,)*3)
        self.assertTrue(all(abs(v)<1e-8 for row in velocity_rows(a,a,.01) for v in row))
        self.assertEqual(MotionPath((a,),(a,),.1).limit_dt(.1,(.01,)*3),.1)

    def test_translation_velocity(self):
        a=primitive('BOX',(.4,.5,.5),(.1,)*3);b=primitive('BOX',(.5,.5,.5),(.1,)*3)
        rows=velocity_rows(a,b,.1)
        self.assertAlmostEqual(rows[0][3],1.)
        self.assertTrue(all(abs(v)<1e-8 for row in rows for v in row[:3]))
