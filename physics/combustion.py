"""One-step fuel kinetics. Temperature is excess above ambient, not absolute K."""
from math import expm1, isfinite
from .config import validate_dt


def react(fuel, temperature, dt, ignition, burn_rate):
    """Exact first-order decay while above ignition; returns consumed fuel."""
    validate_dt(dt)
    if not all(isfinite(v) for v in (fuel,temperature,ignition,burn_rate)) or min(fuel,ignition,burn_rate)<0:
        raise ValueError("Invalid combustion state")
    return fuel * -expm1(-burn_rate*dt) if temperature >= ignition else 0.
