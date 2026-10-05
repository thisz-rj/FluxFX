"""Wall-clock accounting, independent of Blender and GPU execution."""
from dataclasses import replace
from math import isfinite
from .emission import Emission

MIN_REMAINDER = 1e-6


class PlaybackClock:
    """Bounded live-preview debt. Discarded time never advances the fluid."""
    def __init__(self, now, max_lag=0.25):
        self.epoch = self.last = now
        self.max_lag = max_lag
        self.debt = self.simulated = self.dropped = 0.0
        self.report = None

    def begin(self, now):
        elapsed = max(0.0, now - self.last)
        self.last = now
        self.debt += elapsed
        dropped = max(0.0, self.debt - self.max_lag)
        self.dropped += dropped
        self.debt -= dropped
        return dropped

    def run(self, advance, budget, clock, max_steps=32, started=None):
        """Budget includes completed GPU work; a started step cannot be interrupted."""
        start = clock() if started is None else started
        count = 0
        while self.debt >= MIN_REMAINDER and count < max_steps:
            if count and clock() - start >= budget:
                break
            dt = advance(self.debt)
            if not isfinite(dt) or not 0 < dt <= self.debt + 1e-10:
                raise ValueError('Playback step must consume positive available time')
            self.debt = max(0.0, self.debt - dt)
            self.simulated += dt
            count += 1
        end = clock()
        cost = end - start
        wall = max(0.0, end - self.epoch)
        lag = self.debt + max(0.0, end - self.last)
        self.report = dict(callback_ms=cost * 1000, substeps=count,
                           speed=self.simulated / wall if wall else 0.0,
                           lag_ms=lag * 1000, dropped_seconds=self.dropped,
                           limited=self.debt >= MIN_REMAINDER)
        # Yield to Blender even while behind; avoid a full extra frame of sleep.
        return 0.001 if self.report['limited'] else max(0.001, 1 / 30 - cost)


def source_span(source, begin, end):
    """Split one sampled swept source into disjoint substep paths."""
    if not 0 <= begin <= end <= 1:
        raise ValueError('Source fractions must be ordered within [0, 1]')
    def point(fraction):
        return tuple(a + (b - a) * fraction for a, b in zip(source.motion.start, source.center))
    return replace(source, center=point(end),
                   motion=Emission(point(begin), source.motion.velocity, source.motion.coupling))
