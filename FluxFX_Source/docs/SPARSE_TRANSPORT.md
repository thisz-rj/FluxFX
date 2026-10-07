# P1.4 — Sparse scalar transport (0.33.0)

P1.4 adds native Metal density advection with cross-brick trilinear sampling,
ping-pong scalar buffers and a matched dense benchmark. It uses prescribed,
constant translation. Sparse MAC velocity, pressure, temperature and combustion
are not part of this milestone; the interactive smoke solver remains dense.

## Run it

Install `fluxfx-0.33.0.zip` in Apple Silicon Blender 5.3 and restart after replacing
a loaded native module. In **Native core · P1.4**, choose **Compare Sparse Density**.
The button runs eight steps at 128³ with 8³ bricks, writes the numerical/timing
report to `FluxFX Sparse Transport.json`, and creates a central density slice
named `FluxFX Sparse Density` in Blender's Image Editor. The test seed and
velocity are fixed; this button does not simulate the scene's emitter objects.
Use at least 17 MiB for Native arena; the default 64 MiB is sufficient.

```python
from fluxfx.native import compare_transport
r = compare_transport(resolution=256, side=8, steps=8,
                      displacement=(0.6, 0.2, 0.1), budget_bytes=256*2**20)
density_bytes = r.pop('density')  # native float32, x-fastest, then y, z
print(r)
```

Supported resolutions: 32, 64, 128, 256. Brick sizes: 8 or 16. Steps: 1–32.
Displacement is voxels per step, finite and at most four in magnitude per axis.
Budget is a per-engine owned-buffer limit, at most 1 GiB. The comparison holds
both sparse and dense engines concurrently, so combined ownership can exceed
one engine's budget. All native GPU resources are released before return.

## Numerical method and support

The seed is a centered unit-density box of side floor(7N/16): 56³ at 128³ and
112³ at 256³, or 8.374% initial occupied volume. Each step backtraces by the
prescribed displacement and samples eight cell-centered values. Integer sample
coordinates are clamped to the domain boundary, matching the existing dense
scalar sampler. Missing bricks return zero. Eight samples are looked up
individually, including diagonal crossings and departures spanning multiple
bricks. No ghost cells are needed for this prototype.

For constant translation, interpolation weights are calculated once from the
fractional displacement rather than subtracting floats from every cell index.
This avoids position-dependent cancellation error. It makes native dense and
sparse output identical in the tested cases; the existing Blender shader differs
slightly because it computes departure positions in world/domain coordinates.

A fixed conservative topology covers the initial box and its complete planned
trajectory. Crucially, support expands by ceil(abs(displacement)) cells per step,
plus a padding cell, to include the numerical spread of repeated interpolation.
Physical displacement alone would truncate small but nonzero density tails.
Topology is built once before stepping and is never deactivated during the run.
P1.3's source-only expiration is intentionally not used to remove transported
density. Dynamic occupancy reduction and safe field-based deactivation remain
future work. Longer trajectories or coarse bricks can consume most of a domain.

`native/transport.mm` owns the native transport implementation and shaders.
C++ initializes fields, submits steps, reads back and compares; Python sends
settings and displays results. One contiguous Metal buffer per engine contains
two float32 fields and lookup metadata. The sparse engine uses the native brick
topology and a small dense brick-coordinate map (not a dense voxel field).
GPU dispatch count is active_bricks × side³; inactive domain voxels are skipped.

## Validation gates

Gates were specified in `scripts/transport_validate.py`:

- Native sparse versus native dense maximum error ≤ 1e-6.
- Independent NumPy and existing Blender shader maximum error ≤ 1e-4.
- Interior benchmark relative density-sum drift ≤ 1e-6.
- Finite, bounded density and exact integer-translation checks.

All 55 checks passed on Apple M5 Pro / Metal, Blender 5.3 Alpha `b2e052b7172a`,
Python 3.13.13. Cases include zero motion, signed integer/fractional motion,
cross-brick transport, boundary exit, both brick sizes, invalid inputs, budget
failure after partial construction and resource cleanup. A separate NumPy
reference uses separable interpolation in double precision for coordinate
weights. The 128³ check also executes the **existing** `transport_scalar.glsl`
with `mac_sample.glsl`, `closed_sample.glsl` and constant MAC textures.

Native sparse/dense maximum and RMS errors were zero at 128³ and 256³. The
existing Blender dense shader differed by at most 9.03e-6 at 128³. Relative
interior density-sum drift was 4.32e-9 at 128³ and 2.44e-9 at 256³. Reported mass
is the sum of voxel density; multiply by cell volume for a physical integral.
Semi-Lagrangian transport is not generally conservative, and boundary outflow
is not covered by the interior mass gate.

## Observed benchmark

Eight steps of (0.6, 0.2, 0.1) voxels/step. GPU values are medians of all eight
completed commands, including the first. Wall totals include submission and
synchronous GPU waits for all eight steps, but exclude setup and final readback.

| Domain | Brick | Sparse GPU memory | Dense GPU memory | Median sparse / dense GPU ms | Eight-step sparse / dense wall ms |
| --- | --- | ---: | ---: | ---: | ---: |
| 128³ | 8³ | 2.87 MiB | 16.00 MiB | 0.255 / 0.473 | 4.05 / 6.94 |
| 128³ | 16³ | 3.91 MiB | 16.00 MiB | 0.102 / 0.106 | 3.41 / 3.05 |
| 256³ | 8³ | 19.37 MiB | 128.00 MiB | 0.484 / 1.251 | 6.40 / 14.48 |
| 256³ | 16³ | 22.81 MiB | 128.00 MiB | 0.826 / 0.849 | 8.81 / 10.78 |

The 256³ 8³ case uses about 85% less owned GPU memory and completed these eight
transport steps about 2.26× faster than this matched native dense implementation.
These are observations from one run, not a guaranteed speedup. GPU clocks/load
and cold commands cause variation; the 128³ 16³ case did not improve wall time.
This comparison does not establish superiority over Blender's full smoke engine.

Memory includes both ping-pong fields, coordinate map, brick coordinates and
alignment padding. It excludes driver/pipeline resources, CPU topology and the
dense CPU output returned for validation (64 MiB at 256³). The comparison's
combined GPU peak is the sum of the two engine columns. The shared shader is
compiled before engine setup timings; compilation and final CPU comparison are
not included in step timings. Topology cost and initialization cost are reported
separately in the raw evidence. No per-step readback is performed.

The actual Blender comparison button, density image and resource release passed.
Regressions passed: 24 region checks, 29 resource checks, 146 standalone Python
tests, and 15 Blender registration/save-load checks. Reports and native hashes
are in `validation/native_p14/`.

Next: P1.5 sparse staggered MAC velocity, with explicit face ownership and
sampling across brick boundaries. This scalar result is not a realtime smoke
frame-rate result: there is no pressure solve, evolving flow or volume renderer
in its timings.
