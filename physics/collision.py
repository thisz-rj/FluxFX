"""Static analytic solids. Transforms map simulation metres to unit primitives."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Collider:
    shape: str
    inverse_rows: tuple

    def __post_init__(self):
        if self.shape not in ('SPHERE', 'BOX'):
            raise ValueError('Collider must be a sphere or box')
        if len(self.inverse_rows) != 3 or any(len(row) != 4 for row in self.inverse_rows):
            raise ValueError('Collider requires three affine inverse rows')
        if not all(isfinite(v) for row in self.inverse_rows for v in row):
            raise ValueError('Collider transform must be finite')
        a,b,c = (row[:3] for row in self.inverse_rows)
        determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
        if abs(determinant) < 1e-12:
            raise ValueError('Collider transform must be invertible')

    def contains(self, point):
        q = tuple(sum(a*b for a,b in zip(row[:3], point))+row[3] for row in self.inverse_rows)
        return sum(v*v for v in q) <= 1 if self.shape == 'SPHERE' else max(abs(v) for v in q) <= 1


def primitive(shape, center, size):
    """Axis-aligned test/convenience descriptor; size is radius or box half-size."""
    if len(center)!=3 or len(size)!=3 or any(not isfinite(v) or v<=0 for v in size):
        raise ValueError('Three positive finite sizes required')
    return Collider(shape, tuple(tuple((1/size[i] if i==j else 0) for j in range(3)) + (-center[i]/size[i],) for i in range(3)))


def raster_reference(grid, colliders):
    return [float(any(c.contains(tuple((v+.5)*h for v,h in zip((x,y,z),grid.cell_size))) for c in colliders))
            for z in range(grid.shape[2]) for y in range(grid.shape[1]) for x in range(grid.shape[0])]
