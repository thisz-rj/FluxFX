"""Conservative component bounds for semi-Lagrangian transport accuracy."""
from math import isfinite, sqrt, hypot
from .config import validate_dt


def choose_timestep(max_dt, cfl, rate, acceleration_rate=0.0, *, quantized=True):
    validate_dt(max_dt)
    if not all(isfinite(v) for v in (cfl,rate,acceleration_rate)) or not 0<cfl<=2 or min(rate,acceleration_rate)<0:
        raise ValueError('CFL and rate bounds must be finite and valid')
    if not quantized:
        if rate*max_dt+acceleration_rate*max_dt*max_dt<=cfl:return max_dt
        # Stable positive root of a*dt² + rate*dt = CFL, with 1% margin.
        denominator=rate+hypot(rate,2*sqrt(acceleration_rate)*sqrt(cfl))
        dt=.99*(2*cfl/denominator)
        if dt<1e-6:raise RuntimeError('Required timestep below 1 microsecond; reduce forces or reset')
        return min(max_dt,dt)
    dt=max_dt
    # Legacy policy for reproducible comparisons with timestep-scaled pressure.
    while rate*dt+acceleration_rate*dt*dt>cfl:
        dt*=0.5
        if dt<1e-6:
            raise RuntimeError('Required timestep below 1 microsecond; reduce forces or reset')
    return dt
