"""P0 descriptors. Coordinates and velocities use metres and seconds."""
from dataclasses import dataclass
from math import ceil, isfinite, prod


@dataclass(frozen=True)
class GridSpec:
    shape: tuple[int, int, int] = (64, 64, 64)
    extent: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def __post_init__(self):
        if len(self.shape) != 3 or any(type(n) is not int or not 2 <= n <= 128 for n in self.shape):
            raise ValueError("P0 grid dimensions must be integers in [2, 128]")
        if len(self.extent) != 3 or any(not isfinite(x) or x <= 0 for x in self.extent):
            raise ValueError("Domain extents must be finite and positive")

    @property
    def cell_size(self):
        return tuple(e / n for e, n in zip(self.extent, self.shape))

    @property
    def face_shapes(self):
        return tuple(tuple(n + int(i == axis) for i, n in enumerate(self.shape)) for axis in range(3))

    @property
    def mac_bytes(self):
        return self.density_bytes + 2 * sum(prod(shape) for shape in self.face_shapes) * 4

    @property
    def density_bytes(self):
        return 2 * prod(self.shape) * 4  # two R32F fields, excludes driver overhead


@dataclass(frozen=True)
class AdvectionSettings:
    velocity: tuple[float, float, float] = (0.0, 0.0, 0.25)
    angular_speed: float = 0.8
    source_center: tuple[float, float, float] = (0.5, 0.5, 0.16)
    source_radius: float = 0.12
    source_rate: float = 2.0
    dissipation: float = 0.1

    def __post_init__(self):
        if len(self.velocity) != 3 or len(self.source_center) != 3:
            raise ValueError("Velocity and source center must have three components")
        values = (*self.velocity, self.angular_speed, *self.source_center,
                  self.source_radius, self.source_rate, self.dissipation)
        if not all(isfinite(v) for v in values):
            raise ValueError("Simulation parameters must be finite")
        if self.source_radius <= 0 or self.source_rate < 0 or self.dissipation < 0:
            raise ValueError("Radius must be positive; source rate and dissipation nonnegative")


def workgroups(shape, local_size=(4, 4, 4)):
    if len(shape) != 3 or len(local_size) != 3 or any(n <= 0 for n in (*shape, *local_size)):
        raise ValueError("Dispatch requires three positive dimensions")
    return tuple(ceil(n / local) for n, local in zip(shape, local_size))


def validate_dt(dt):
    if not isfinite(dt) or not 0 < dt <= 0.1:
        raise ValueError("P0 timestep must be finite and in (0, 0.1] seconds")
