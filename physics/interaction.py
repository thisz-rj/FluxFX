"""Settings that can change between GPU steps without reallocating fields."""
from dataclasses import fields
from .pressure import PressureSettings

LIVE_FIELDS = frozenset({"turbulence_strength","turbulence_scale","turbulence_speed","turbulence_seed","turbulence_octaves","turbulence_limit","turbulence_mask","turbulence_threshold","fuel_source_rate", "ignition_temperature", "burn_rate", "heat_yield", "smoke_yield", "velocity_advection", "timestep_policy", "density_mode", "source_profile", "scalar_advection", "vorticity_strength", "vorticity_limit", "source_center", "source_radius", "source_rate", "dissipation",
    "heat_source_rate", "cooling", "thermal_lift", "density_weight", "pressure_iterations", "pressure_cycles"})


def reset_signature(settings):
    return tuple((f.name, getattr(settings, f.name)) for f in fields(settings)
                 if f.name not in LIVE_FIELDS)


def validate_live_update(current, candidate):
    if type(candidate) is not PressureSettings:
        raise TypeError("Live controls require PressureSettings")
    if reset_signature(current) != reset_signature(candidate):
        raise ValueError("Initial conditions changed; Reset required")
