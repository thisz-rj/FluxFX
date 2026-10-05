import unittest
from fluxfx.physics.solid_hierarchy import build_hierarchy


def apply(shape,edges,p):
    result=[0.]*len(p)
    for i in range(len(p)):
        for a,s in enumerate((1,shape[0],shape[0]*shape[1])):
            w=edges[4*i+a]
            if w:
                d=w*(p[i+s]-p[i]);result[i]+=d;result[i+s]-=d
    return result


class SolidHierarchyTests(unittest.TestCase):
    def test_galerkin_operator(self):
        shape=(8,8,8)
        mask=[float(2<=x<4 and 2<=y<4 and 2<=z<4)
              for z in range(8) for y in range(8) for x in range(8)]
        levels=build_hierarchy(shape,(1.,2.,3.),mask)
        self.assertEqual(len(levels),2)
        coarse,edges=levels[1]
        p=[float((i*13)%17) for i in range(64)]
        finep=[p[x//2+4*(y//2+4*(z//2))] for z in range(8) for y in range(8) for x in range(8)]
        fine_result=apply(shape,levels[0][1],finep)
        restricted=[sum(fine_result[2*x+dx+8*(2*y+dy+8*(2*z+dz))]
                    for dz in range(2) for dy in range(2) for dx in range(2))/8
                    for z in range(4) for y in range(4) for x in range(4)]
        for a,b in zip(restricted,apply(coarse,edges,p)):self.assertAlmostEqual(a,b,places=4)

    def test_disconnected_children_stop_coarsening(self):
        mask=[1.]*512;mask[0]=mask[1+8+64]=0
        self.assertEqual(len(build_hierarchy((8,)*3,(1.,)*3,mask)),1)

    def test_slab_has_no_coarse_edges_across_wall(self):
        mask=[float(z in (3,4)) for z in range(8) for y in range(8) for x in range(8)]
        levels=build_hierarchy((8,)*3,(1.,)*3,mask)
        shape,edges=levels[-1]
        self.assertEqual(shape,(4,)*3)
        self.assertTrue(all(edges[4*(x+4*(y+4))+2]==0 for y in range(4) for x in range(4)))

    def test_zero_graph_is_finite_and_has_no_edges(self):
        for shape,edges in build_hierarchy((16,)*3,(1.,)*3,[1.]*4096):
            self.assertTrue(all(v==0 for v in edges))
