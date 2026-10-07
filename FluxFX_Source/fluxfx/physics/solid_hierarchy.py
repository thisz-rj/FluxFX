"""Piecewise-constant Galerkin aggregation of the masked pressure graph.

Each record stores positive-axis edge weights and an active flag. Restriction
is P^T/8, hence coarse edges are boundary sums / 8. Never merge disconnected
children: stop before an aggregate would bridge a wall or isolated pocket.
"""
from array import array
from math import prod


def build_hierarchy(shape, extent, mask):
    if len(mask) != prod(shape):
        raise ValueError('Mask size must match grid')
    nx, ny, nz = shape
    strides = (1, nx, nx*ny)
    fine = array('f', [0.0]) * (4*prod(shape))
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                i=x+nx*(y+ny*z)
                if mask[i] > .5: continue
                fine[4*i+3]=1
                for a,c in enumerate((x,y,z)):
                    if c+1<shape[a] and mask[i+strides[a]]<=.5:
                        fine[4*i+a]=(shape[a]/extent[a])**2
    levels=[(shape,fine)]
    while min(shape)>=8 and all(n%2==0 for n in shape):
        nx,ny,nz=shape; strides=(1,nx,nx*ny)
        coarse_shape=tuple(n//2 for n in shape)
        coarse=array('f',[0.0])*(4*prod(coarse_shape))
        for z in range(coarse_shape[2]):
            for y in range(coarse_shape[1]):
                for x in range(coarse_shape[0]):
                    ids=[2*x+dx+nx*(2*y+dy+ny*(2*z+dz))
                         for dz in range(2) for dy in range(2) for dx in range(2)]
                    active={j for j,i in enumerate(ids) if fine[4*i+3]>0}
                    if active:
                        seen={next(iter(active))}; pending=list(seen)
                        while pending:
                            j=pending.pop()
                            for a in range(3):
                                k=j^(1<<a)
                                lower=k if j & (1<<a) else j
                                if k in active and k not in seen and fine[4*ids[lower]+a]>0:
                                    seen.add(k);pending.append(k)
                        if seen!=active:
                            return levels  # No fictitious connection through an aggregate.
                    ci=x+coarse_shape[0]*(y+coarse_shape[1]*z)
                    coarse[4*ci+3]=float(bool(active))
                    for a in range(3):
                        coarse[4*ci+a]=sum(fine[4*i+a] for j,i in enumerate(ids) if j & (1<<a))/8
        shape,fine=coarse_shape,coarse
        levels.append((shape,fine))
    return levels


def graph_inverse(shape, edges):
    """Small graph pseudoinverse, with one constant null mode per component.

    NumPy is bundled with Blender; import here keeps hierarchy construction and
    topology tests usable without Blender or NumPy.
    """
    import numpy as np
    n=prod(shape)
    if n>256:raise ValueError('Direct coarse solve is limited to 256 cells')
    matrix=np.zeros((n,n),dtype=np.float64)
    strides=(1,shape[0],shape[0]*shape[1])
    for i in range(n):
        for a,stride in enumerate(strides):
            w=edges[4*i+a]
            if w:
                j=i+stride
                matrix[i,i]-=w;matrix[j,j]-=w
                matrix[i,j]+=w;matrix[j,i]+=w
    return np.linalg.pinv(matrix,rcond=1e-12,hermitian=True).astype(np.float32).ravel().tolist()
