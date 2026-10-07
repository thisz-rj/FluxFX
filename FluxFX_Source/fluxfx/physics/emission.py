"""Per-step source motion, independent of Blender and GPU storage."""
from dataclasses import dataclass
from math import isfinite, sqrt


@dataclass(frozen=True)
class Emission:
    start: tuple
    velocity: tuple = (0., 0., 0.)
    coupling: float = 0.

    def __post_init__(self):
        if len(self.start) != 3 or len(self.velocity) != 3 or not all(isfinite(x) for x in (*self.start, *self.velocity, self.coupling)) or self.coupling < 0:
            raise ValueError("Invalid emission parameters")


def motion_velocity(previous, current, interval, inheritance, jet, speed_limit):
    """Bound inherited translation before adding the directional jet."""
    if any(len(v)!=3 for v in (previous,current,jet)) or not all(isfinite(v) for v in (*previous,*current,*jet,interval,inheritance,speed_limit)) or interval <= 0 or inheritance < 0 or speed_limit <= 0:
        raise ValueError("Invalid motion interval or limits")
    velocity = tuple((b-a)/interval*inheritance for a,b in zip(previous,current))
    speed = sqrt(sum(v*v for v in velocity))
    factor = min(1., speed_limit/max(speed, 1e-20))
    return tuple(v*factor+j for v,j in zip(velocity,jet))


MAX_SOURCES = 8
SOURCE_TABLE_SHAPE = (4, 4, MAX_SOURCES)


@dataclass(frozen=True)
class Source:
    center: tuple
    radius: float
    density_rate: float
    heat_rate: float
    motion: Emission
    density_mode: str = "RATE"
    profile: str = "SOFT"
    fuel_rate: float = 0.0

    def __post_init__(self):
        if not isfinite(self.fuel_rate) or self.fuel_rate<0:raise ValueError("Fuel rate must be finite and nonnegative")
        if self.density_mode not in {"RATE","TARGET"} or self.profile not in {"SOFT","SOLID"}:raise ValueError("Unknown source mode/profile")
        if len(self.center)!=3 or not all(isfinite(v) for v in (*self.center,self.radius,self.density_rate,self.heat_rate)) or self.radius<=0 or self.density_rate<0 or not isinstance(self.motion,Emission):
            raise ValueError("Invalid spherical source")


def pack_sources(sources):
    """One 16-float plane per sphere. Upload only when source data changes."""
    if len(sources)>MAX_SOURCES:
        raise ValueError("At most eight sources are supported")
    data=[]
    for source in sources:
        if not isinstance(source,Source):raise TypeError("Expected Source")
        data.extend((*source.center,source.radius,*source.motion.start,source.motion.coupling,
                     *source.motion.velocity,source.density_rate,source.heat_rate,float(source.density_mode=="TARGET"),float(source.profile=="SOLID"),source.fuel_rate))
    return tuple(data+[0.]*(16*MAX_SOURCES-len(data)))
