"""Small CPU oracle for tests only. Never used by interactive simulation.

Scalar fields are flat x-fast arrays: x + nx * (y + ny * z).
Zero extension at cell centers defines the open/outflow boundary.
"""
from math import exp, floor

from .config import validate_dt


def velocity_at(p, extent, settings):
    x, y, _ = p
    vx, vy, vz = settings.velocity
    w = settings.angular_speed
    return vx - w * (y - extent[1] / 2), vy + w * (x - extent[0] / 2), vz


def source_weight(p, settings):
    r2 = sum((a - b) ** 2 for a, b in zip(p, settings.source_center))
    return max(1.0 - r2 / settings.source_radius ** 2, 0.0) ** 2


def sample_zero(field, shape, cell_position):
    nx, ny, nz = shape
    base = tuple(floor(q) for q in cell_position)
    frac = tuple(q - b for q, b in zip(cell_position, base))
    total = 0.0
    for dz in (0, 1):
        for dy in (0, 1):
            for dx in (0, 1):
                x, y, z = (base[i] + d for i, d in enumerate((dx, dy, dz)))
                if 0 <= x < nx and 0 <= y < ny and 0 <= z < nz:
                    weight = 1.0
                    for t, d in zip(frac, (dx, dy, dz)):
                        weight *= t if d else 1 - t
                    total += weight * field[x + nx * (y + ny * z)]
    return total


def advect(field, grid, settings, dt):
    validate_dt(dt)
    nx, ny, nz = grid.shape
    if len(field) != nx * ny * nz:
        raise ValueError("Field length does not match grid")
    result = []
    h = grid.cell_size
    for z in range(nz):
        for y in range(ny):
            for x in range(nx):
                p = tuple((q + 0.5) * d for q, d in zip((x, y, z), h))
                v = velocity_at(p, grid.extent, settings)
                mid = tuple(q - 0.5 * dt * u for q, u in zip(p, v))
                vm = velocity_at(mid, grid.extent, settings)
                back = tuple((q - dt * u) / d - 0.5 for q, u, d in zip(p, vm, h))
                density = sample_zero(field, grid.shape, back) * exp(-settings.dissipation * dt)
                result.append(density + dt * settings.source_rate * source_weight(p, settings))
    return result
