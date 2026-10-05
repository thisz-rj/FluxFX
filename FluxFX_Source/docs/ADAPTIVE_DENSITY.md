# P1.8 adaptive density growth — 0.40.0

Density support now grows before transport rather than relying on the fixed
central region from 0.39. Pressure and velocity remain full-domain dense arrays.
The diagnostic begins with one density brick, deliberately too small for the
source, and appends missing bricks as required. It never deactivates a brick.

## Coverage and preservation

After velocity transport and global projection, a Metal preflight visits every
domain cell. Using the same RK2 backtrace as density transport, it marks a
potential destination whenever any interpolation sample has positive old
density or positive analytic emission. It also marks every emission cell's
brick. Interpolation weights are not used to discard samples, making marking
conservative. There is no positive-density threshold that can silently discard
small tails. Domain clamping matches the transport kernel.

The CPU reads only brick flags, appends new coordinates with stable IDs and
builds the map in native C++. New storage is cleared. A GPU copy preserves the
existing density prefix and the global fields; a byte-for-byte check verifies
the density copy before swapping buffers. New density cells start at zero.
The scratch density buffer is then overwritten by injection. Required bricks
are allocated before injection/advection, so support can grow across gaps
without waiting for smoke to arrive at an existing brick boundary.

This is grow-only allocation, not general remapping, reclamation or compaction.
The preflight assumes this nonnegative scalar, analytic emitter and existing
transport discretization; other source/transport models require new validation.
All physics runs in Metal; Python only invokes the diagnostic and reads results.

## Validation

M5 Pro / Metal, graphical Blender 5.3.0 Alpha `b2e052b7172a`, Python 3.13.13.
231 checks pass, including the independent 32³ NumPy reference, 64³/128³ dense
comparisons, both brick sizes, five velocity seeds, three emission schedules,
and horizons up to 16 steps. The eight-step benchmarks have measured maximum
errors of zero for density, pressure, velocity and divergence. Gates are 1e-6
native error, 1e-4 CPU error and 1e-5 mass disagreement. A 64³ sequence checks
every horizon from one to eight steps, monotonic brick counts and repeated growth.
`preserved_bytes` records existing scalar bytes verified through growth copies.

Budget tests cover initialization failure and a 128³/120 MiB case that can
initialize but rejects the first transient growth allocation. Owned-buffer
counts return to baseline after failure and success. The budget is per engine
including its hierarchy and simultaneous old/replacement allocations during
growth. The dense comparison is separately budgeted; the pair's peak is the
adaptive peak plus dense bytes. Host vectors and Metal driver overhead are not
included in the owned GPU buffer budget.

| Domain / brick | Final density bricks | Growth events | Final MiB | Peak adaptive MiB | Adaptive wall ms | Dense wall ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64³ / 8³ | 41 | 8 | 10.844 | 21.088 | 73.08 | 62.31 |
| 64³ / 16³ | 8 | 1 | 10.918 | 21.045 | 67.93 | 63.25 |
| 128³ / 8³ | 91 | 8 | 85.451 | 166.291 | 345.03 | 292.67 |
| 128³ / 16³ | 22 | 5 | 85.653 | 166.670 | 326.42 | 293.16 |

Single-run timings cover all eight completed steps with eight V-cycles per
step. They include support scans, GPU waits, host topology updates, growth
allocation/zeroing, copy verification and transport, but exclude initial setup,
compilation and final readback. They are not viewport FPS. At 128³, dense owned
memory is 100.948 MiB; adaptive final memory is lower, but adaptive peak memory
is substantially higher. No net performance advantage is claimed.

The buffer currently contains both dense fields and sparse density. Growth
therefore duplicates the main allocation temporarily. `peak_sparse_bytes`
reports that peak plus hierarchy; `sparse_bytes` reports final allocation.
`preflight_ms` includes detection, synchronization, topology and growth work.
GPU timing includes the preflight and copy commands, but excludes host work.
`density_bricks` reports density allocation; legacy `active_bricks` still
reports global pressure support. Smoke occupancy is separate from both.

Regression checks pass: fixed hybrid 209, global coverage 115, coupled 113,
multigrid 171, projection 154, MAC 96, scalar transport 55, regions 24,
resources 29, standalone Python 146 and Blender save/load 15. The new Blender
operator and cleanup check pass. [Reports and hashes](validation/native_p18_adaptive)
preserve the evidence.

## Run

Build with `python3 scripts/build_native.py` on Apple Silicon with Xcode;
package with `python3 scripts/package.py`. Install `fluxfx-0.40.0.zip` in
Blender 5.3 Apple Silicon and restart Blender when replacing a loaded native
binary. **Native core · P1.8 → Compare Adaptive Density** runs a fixed 64³ test
and writes **FluxFX Adaptive Density.json** in Blender's Text Editor.
Interactive smoke still uses the established dense solver.

The native wrapper is `fluxfx.native.compare_adaptive_coupled`. Run
`scripts/adaptive_validate.py` and `scripts/adaptive_ui_validate.py` (with the
addon registered) in graphical Blender with the repository on Python's import
path. Reports go to `test-results`. Background Blender remains suitable only
for non-GPU checks in this setup; no new Blender API limitation was encountered.

## Next gate

Split density into independent, capacity-managed buffers so growth does not
copy the global fields. Then replace the full-domain preflight with a validated
conservative local candidate set. Preserve this slow scan as a correctness
oracle. Deactivation/reuse and persistent simulation remain separate work.
P1.8 is still open: no 256³/8% occupancy benchmark or complete 0.28 feature
parity has been established. Temperature, fire, collisions and liquids remain
deferred in the native engine.

## Follow-up in 0.41

[Independent density capacity](DENSITY_CAPACITY.md) removes global-field copies
and reuses spare scalar capacity. The 0.40 path remains available for matched
regression and performance comparisons.
