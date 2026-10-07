"""P0.4 temperature is a signed excess above ambient, in kelvin."""
from dataclasses import dataclass
from math import isfinite
from .config import AdvectionSettings


@dataclass(frozen=True)
class ThermalSettings(AdvectionSettings):
    velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    angular_speed: float = 0.0
    initial_temperature: float = 100.0
    heat_source_rate: float = 100.0
    cooling: float = 0.5
    thermal_lift: float = 0.005
    density_weight: float = 0.05

    def __post_init__(self):
        super().__post_init__()
        if not all(isfinite(v) for v in (self.initial_temperature, self.heat_source_rate,
                                         self.cooling, self.thermal_lift, self.density_weight)):
            raise ValueError("Thermal parameters must be finite")
        if min(self.cooling, self.thermal_lift, self.density_weight) < 0:
            raise ValueError("Cooling, thermal lift, and density weight must be nonnegative")


def acceleration(temperature, density, settings):
    """Positive is +Z; coefficients include the chosen gravity scaling."""
    return settings.thermal_lift * temperature - settings.density_weight * density
