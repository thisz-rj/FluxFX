"""Neumann pseudoinverse for a tiny, cell-centered 4-cubed pressure grid."""
from functools import lru_cache
from math import cos, sin, pi, sqrt


@lru_cache(maxsize=8)
def coarse_inverse(extent):
    """Rows map a mean-free RHS to zero-mean pressure. No NumPy dependency."""
    n = 4
    cells = [(x, y, z) for z in range(n) for y in range(n) for x in range(n)]
    modes = []
    for mode in cells[1:]:
        eigenvalue = sum(-4 * (n / extent[a]) ** 2 * sin(pi * mode[a] / (2*n)) ** 2
                         for a in range(3))
        basis = []
        for cell in cells:
            value = 1.0
            for a in range(3):
                k = mode[a]
                value *= sqrt((1 if k == 0 else 2) / n) * cos(pi*k*(cell[a]+.5)/n)
            basis.append(value)
        modes.append((eigenvalue, basis))
    return tuple(sum(basis[i]*basis[j]/eigenvalue for eigenvalue,basis in modes)
                 for i in range(64) for j in range(64))
