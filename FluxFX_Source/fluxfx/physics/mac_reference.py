"""Small CPU MAC oracle, used only in tests. Face data is x-fast."""
from math import floor, exp
from .reference import velocity_at, sample_zero, source_weight
from .config import validate_dt

OFFSETS = ((0, .5, .5), (.5, 0, .5), (.5, .5, 0))


def positions(grid, axis):
    nx, ny, nz = grid.face_shapes[axis]
    offset = OFFSETS[axis]
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                yield tuple((n + o) * h for n, o, h in zip((x, y, z), offset, grid.cell_size))


def seed_velocity(grid, settings):
    return tuple([velocity_at(p, grid.extent, settings)[axis] for p in positions(grid, axis)]
                 for axis in range(3))


def sample_clamp(field, shape, q):
    q = tuple(max(0, min(n - 1, v)) for n, v in zip(shape, q))
    lo = tuple(floor(v) for v in q)
    t = tuple(v - b for v, b in zip(q, lo))
    total = 0.0
    for z in (0, 1):
        for y in (0, 1):
            for x in (0, 1):
                indices = [min(b + d, n - 1) for b, d, n in zip(lo, (x, y, z), shape)]
                weight = 1.0
                for a, d in zip(t, (x, y, z)):
                    weight *= a if d else 1 - a
                ix, iy, iz = indices
                total += weight * field[ix + shape[0] * (iy + shape[1] * iz)]
    return total


def sample_velocity(components, grid, p):
    return tuple(sample_clamp(field, shape, tuple(v / h - o for v, h, o in zip(p, grid.cell_size, offset)))
                 for field, shape, offset in zip(components, grid.face_shapes, OFFSETS))


def backtrace(components, grid, p, dt):
    v = sample_velocity(components, grid, p)
    mid = tuple(a - .5 * dt * b for a, b in zip(p, v))
    vm = sample_velocity(components, grid, mid)
    return tuple(a - dt * b for a, b in zip(p, vm))


def advect_velocity(components, grid, dt):
    validate_dt(dt)
    return tuple([sample_velocity(components, grid, backtrace(components, grid, p, dt))[axis]
                  for p in positions(grid, axis)] for axis in range(3))


def advect_density(field, components, grid, settings, dt):
    validate_dt(dt)
    nx, ny, nz = grid.shape
    result = []
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                p = tuple((i + .5) * h for i, h in zip((x, y, z), grid.cell_size))
                back = backtrace(components, grid, p, dt)
                q = tuple(a / h - .5 for a, h in zip(back, grid.cell_size))
                result.append(sample_zero(field, grid.shape, q) * exp(-settings.dissipation * dt)
                              + dt * settings.source_rate * source_weight(p, settings))
    return result
