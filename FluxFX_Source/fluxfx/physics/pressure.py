"""Closed-box pressure settings and diagnostic statistics."""
from dataclasses import dataclass
from math import isfinite, fsum, sqrt
from .thermal import ThermalSettings


@dataclass(frozen=True)
class PressureSettings(ThermalSettings):
    turbulence_strength: float = 0.0
    turbulence_scale: float = 0.5
    turbulence_speed: float = 0.5
    turbulence_seed: int = 0
    turbulence_octaves: int = 3
    turbulence_limit: float = 2.0
    turbulence_mask: str = 'DENSITY'
    turbulence_threshold: float = 0.2
    combustion_enabled: bool = False
    fuel_source_rate: float = 1.0
    ignition_temperature: float = 150.0
    burn_rate: float = 4.0
    heat_yield: float = 600.0
    smoke_yield: float = 1.0
    moving_colliders: bool = False
    velocity_advection: str = "SEMI_LAGRANGIAN"
    timestep_policy: str = "AUTO"
    pressure_warm_start: str = "AUTO"
    coarse_solver: str = "DIRECT"
    density_mode: str = "RATE"
    source_profile: str = "SOFT"
    scalar_advection: str = "SEMI_LAGRANGIAN"
    vorticity_strength: float = 0.0
    vorticity_limit: float = 2.0
    pressure_solver: str = "AUTO"
    pressure_cycles: int = 2
    pressure_iterations: int = 80
    pressure_relaxation: float = 2.0 / 3.0
    pressure_cold_multiplier: int = 4

    def __post_init__(self):
        super().__post_init__()
        for value,low,high in ((self.turbulence_strength,0,20),(self.turbulence_scale,.01,4),
                (self.turbulence_speed,0,10),(self.turbulence_limit,.01,20),(self.turbulence_threshold,.001,2000)):
            if not isfinite(value) or not low<=value<=high:raise ValueError('Invalid turbulence parameter')
        if type(self.turbulence_seed) is not int or not 0<=self.turbulence_seed<=65535:raise ValueError('Invalid turbulence seed')
        if type(self.turbulence_octaves) is not int or not 1<=self.turbulence_octaves<=4:raise ValueError('Use one to four turbulence scales')
        if self.turbulence_mask not in {'ALL','DENSITY','HEAT'}:raise ValueError('Invalid turbulence mask')
        if type(self.combustion_enabled) is not bool:raise ValueError("Combustion enabled must be boolean")
        if not all(isfinite(v) and v>=0 for v in (self.fuel_source_rate,self.ignition_temperature,self.burn_rate,self.heat_yield,self.smoke_yield)):
            raise ValueError("Combustion parameters must be finite and nonnegative")
        if self.coarse_solver not in {"DIRECT","SMOOTH"}:raise ValueError("Unknown coarse pressure solver")
        if self.timestep_policy not in {"AUTO","CONTINUOUS","QUANTIZED"}:raise ValueError("Unknown timestep policy")
        if self.velocity_advection not in {"SEMI_LAGRANGIAN","MACCORMACK"}:raise ValueError("Unknown velocity advection")
        if self.pressure_warm_start not in {"AUTO","IMPULSE","LEGACY"}:raise ValueError("Unknown pressure warm start")
        if self.density_mode not in {"RATE","TARGET"} or self.source_profile not in {"SOFT","SOLID"}:raise ValueError("Unknown emission mode/profile")
        if self.scalar_advection not in {"SEMI_LAGRANGIAN","MACCORMACK"}:raise ValueError("Unknown scalar advection")
        if not isfinite(self.vorticity_strength) or not 0<=self.vorticity_strength<=20:raise ValueError("Curl strength must lie in [0,20]")
        if not isfinite(self.vorticity_limit) or not 0<self.vorticity_limit<=20:raise ValueError("Curl acceleration limit must lie in (0,20]")
        if self.pressure_solver not in {"AUTO", "JACOBI", "MULTIGRID"}:
            raise ValueError("Unknown pressure solver")
        if type(self.pressure_cycles) is not int or not 1 <= self.pressure_cycles <= 16:
            raise ValueError("Multigrid cycles must be an integer in [1, 16]")
        if type(self.pressure_iterations) is not int or not 1 <= self.pressure_iterations <= 4096:
            raise ValueError("Pressure iterations must be an integer in [1, 4096]")
        if type(self.pressure_cold_multiplier) is not int or not 1 <= self.pressure_cold_multiplier <= 8:
            raise ValueError("Cold-start multiplier must be an integer in [1, 8]")
        if not isfinite(self.pressure_relaxation) or not 0 < self.pressure_relaxation < 1:
            raise ValueError("Jacobi relaxation must lie strictly between zero and one")


def divergence_stats(before, after):
    if not before or len(before) != len(after):
        raise ValueError("Divergence arrays must be nonempty and equal in length")
    if not all(isfinite(v) for v in (*before, *after)):
        raise ValueError("Non-finite divergence")
    rms_before = sqrt(fsum(v * v for v in before) / len(before))
    rms_after = sqrt(fsum(v * v for v in after) / len(after))
    ratio = rms_after / rms_before if rms_before > 0 else (0.0 if rms_after == 0 else None)
    return {"rms_before": rms_before, "rms_after": rms_after, "ratio": ratio,
            "max_before": max(abs(v) for v in before), "max_after": max(abs(v) for v in after),
            "mean_before": fsum(before) / len(before), "mean_after": fsum(after) / len(after)}
