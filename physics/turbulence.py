"""Deterministic transverse Fourier forcing, expressed in simulation metres."""
from math import pi,sqrt
from random import Random

def spectrum(grid, settings):
    rng=Random(settings.turbulence_seed);rows=[]
    h=max(grid.cell_size)
    for octave in range(4):
        wavelength=settings.turbulence_scale/2**octave
        fade=max(0.,min(1.,(wavelength/h-4)/4)) if octave<settings.turbulence_octaves else 0.
        for _ in range(3):
            k=[rng.uniform(-1,1) for _ in range(3)];length=sqrt(sum(v*v for v in k));k=[v/length for v in k]
            r=[rng.uniform(-1,1) for _ in range(3)]
            a=[k[1]*r[2]-k[2]*r[1],k[2]*r[0]-k[0]*r[2],k[0]*r[1]-k[1]*r[0]]
            length=max(sqrt(sum(v*v for v in a)),1e-12)
            # Sum of amplitude norms <= 1; unresolved bands smoothly vanish.
            weight=fade*2**(-octave)/(3*1.875)
            rows.extend([*(v*2*pi/wavelength for v in k),rng.uniform(-pi,pi),
                         *(v/length*weight for v in a),rng.uniform(.7,1.3)*2*pi])
    return tuple(rows)
