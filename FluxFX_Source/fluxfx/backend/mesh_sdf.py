"""Reset-time CPU BVH distance/sign queries. GPU stepping remains mesh-independent."""
from math import sqrt
from time import perf_counter
from ..physics.mesh import validate_mesh


def build_sdf(grid,mesh):
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    start=perf_counter();validate_mesh(mesh)
    vertices=[Vector(v) for v in mesh.vertices]
    tree=BVHTree.FromPolygons(vertices,mesh.triangles,all_triangles=True)
    # Nonadjacent intersections are unsupported; adjacency contacts are expected.
    for a,b in tree.overlap(tree):
        if a!=b and not set(mesh.triangles[a]).intersection(mesh.triangles[b]):
            raise ValueError('Self-intersecting mesh collider; repair intersections before Reset')
    low=tuple(min(v[i] for v in mesh.vertices) for i in range(3))
    high=tuple(max(v[i] for v in mesh.vertices) for i in range(3))
    span=sqrt(sum((b-a)**2 for a,b in zip(low,high)))
    epsilon=max(1e-8,span*1e-7)
    directions=[Vector(d).normalized() for d in ((1,.371,.529),(.217,1,.613),(.419,.283,1))]
    volume6=sum(vertices[a].dot(vertices[b].cross(vertices[c])) for a,b,c in mesh.triangles)
    if abs(volume6)<1e-12:raise ValueError('Mesh has negligible enclosed volume')
    orientation=1. if volume6>0 else -1.
    def inside(p):
        # For a consistently wound closed surface, an inside ray first exits;
        # an outside ray first enters. Three directions avoid tangent ambiguity.
        votes=0
        for direction in directions:
            hit,normal,_,_=tree.ray_cast(p,direction,span*3+1)
            if hit is not None and normal.dot(direction)*orientation>1e-7:votes+=1
        return votes>=2
    values=[];occupied=0
    for z in range(grid.shape[2]):
        for y in range(grid.shape[1]):
            for x in range(grid.shape[0]):
                p=Vector(tuple((i+.5)*h for i,h in zip((x,y,z),grid.cell_size)))
                _,_,_,distance=tree.find_nearest(p)
                if distance is None:raise ValueError('Mesh distance query failed')
                within=all(a<=v<=b for a,v,b in zip(low,p,high))
                solid=distance<=epsilon or (within and inside(p))
                occupied+=int(solid);values.append(-max(distance,epsilon) if solid else distance)
    if occupied==0:raise ValueError('Mesh occupies no grid cells; move it inside the domain or increase resolution/thickness')
    warnings=[]
    if min(b-a for a,b in zip(low,high))<2*min(grid.cell_size):
        warnings.append('Mesh bounds are thinner than two cells; collision detail may be lost')
    return values,dict(triangles=len(mesh.triangles),occupied_cells=occupied,build_seconds=perf_counter()-start,
                       minimum_distance=min(values),maximum_distance=max(values),warnings=warnings)
