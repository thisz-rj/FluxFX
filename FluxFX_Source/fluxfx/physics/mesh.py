"""Immutable evaluated mesh geometry in simulation metres; no Blender imports."""
from dataclasses import dataclass
from math import isfinite
from collections import defaultdict

@dataclass(frozen=True)
class MeshCollider:
    vertices: tuple
    triangles: tuple
    shape: str = 'MESH'


def validate_mesh(mesh):
    vertices,triangles=mesh.vertices,mesh.triangles
    if not triangles or len(triangles)>50000:
        raise ValueError('Mesh collider needs 1–50,000 evaluated triangles')
    if not all(len(v)==3 and all(isfinite(x) for x in v) for v in vertices):
        raise ValueError('Mesh coordinates must be finite')
    edges=defaultdict(list)
    for index,tri in enumerate(triangles):
        if len(tri)!=3 or len(set(tri))!=3 or any(type(i) is not int or not 0<=i<len(vertices) for i in tri):
            raise ValueError('Invalid mesh triangle')
        a,b,c=(vertices[i] for i in tri)
        u=tuple(y-x for x,y in zip(a,b));v=tuple(y-x for x,y in zip(a,c))
        cross=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        if sum(x*x for x in cross)<1e-20:raise ValueError('Degenerate mesh triangle; clean the mesh before Reset')
        for a,b in zip(tri,tri[1:]+tri[:1]):edges[min(a,b),max(a,b)].append((a,b,index))
    if any(len(e)!=2 for e in edges.values()):
        raise ValueError('Mesh must be closed and manifold: every edge needs exactly two faces')
    if any(e[0][:2]==e[1][:2] for e in edges.values()):
        raise ValueError('Mesh winding is inconsistent; recalculate normals before Reset')
    # Reject disconnected/nested shells until a defined union/cavity policy exists.
    neighbours=defaultdict(list)
    for e in edges.values():
        a,b=e[0][2],e[1][2];neighbours[a].append(b);neighbours[b].append(a)
    seen={0};todo=[0]
    while todo:
        for i in neighbours[todo.pop()]:
            if i not in seen:seen.add(i);todo.append(i)
    if len(seen)!=len(triangles):raise ValueError('Use one connected closed shell per mesh collider')
    return len(triangles)
