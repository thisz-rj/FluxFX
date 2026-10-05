"""Independent small-grid CPU reference for P0.4 validation only."""
from .thermal import acceleration
from .mac_reference import advect_velocity, advect_density


def apply_buoyancy(velocity, density, temperature, grid, settings, dt):
    nx, ny, nz = grid.shape
    w = []
    for z in range(nz + 1):
        for y in range(ny):
            for x in range(nx):
                below = x + nx * (y + ny * max(z - 1, 0))
                above = x + nx * (y + ny * min(z, nz - 1))
                theta = (temperature[below] + temperature[above]) * .5
                rho = (density[below] + density[above]) * .5
                i = x + nx * (y + ny * z)
                w.append(velocity[2][i] + dt * acceleration(theta, rho, settings))
    return velocity[0][:], velocity[1][:], w


def step(density, temperature, velocity, grid, settings, dt):
    velocity = advect_velocity(velocity, grid, dt)
    velocity = apply_buoyancy(velocity, density, temperature, grid, settings, dt)
    density_next = advect_density(density, velocity, grid, settings, dt)
    # Reference scalar transport accepts signed source rates; dataclass validation
    # keeps density rates nonnegative, so supply just the scalar attributes here.
    from types import SimpleNamespace
    scalar = SimpleNamespace(source_center=settings.source_center, source_radius=settings.source_radius,
                             source_rate=settings.heat_source_rate, dissipation=settings.cooling)
    temperature_next = advect_density(temperature, velocity, grid, scalar, dt)
    return density_next, temperature_next, velocity
