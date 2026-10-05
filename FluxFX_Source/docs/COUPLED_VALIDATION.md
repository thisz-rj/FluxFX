# P1.8 — Coupled baseline and dense-equivalence audit (0.37.0)

**P1.8's unrestricted dense-equivalence gate remains open.** The native coupled
implementation passes 113 checks when both paths use the same pressure region.
The audit against an unrestricted native dense domain fails the predefined
maximum-error limits. Package 0.37.0 delivers the coupled baseline and exposes
this failure; it does not declare the sparse engine equivalent to dense smoke.

## Run

Install `fluxfx-0.37.0.zip` in Blender 5.3 on Apple Silicon. Choose
**Native core · P1.8 → Compare Coupled Engine**. The fixed 64³, three-step test
writes `FluxFX Coupled Engine.json`. Its PASS applies only to matched-region
implementation checks; the report states that scope explicitly. Interactive
viewport smoke remains the existing dense solver.

```python
from fluxfx.native import compare_coupled
report = compare_coupled(resolution=128, side=8, steps=8, cycles=8,
                         mode=1, schedule=1, dense_full=False,
                         budget_bytes=256 * 2**20)
for key in ('density', 'faces', 'pressure', 'before', 'after'):
    report.pop(key)
print(report)
# Set dense_full=True to audit against an unrestricted dense solve.
```

Supported grids: 32/64/128; bricks: 8/16; steps and cycles: 1–16. Mode uses P1.6's
prescribed velocity/pressure-region cases. Schedule 0 is stationary emission,
1 moves the source sinusoidally in X, and 2 alternates emission on/off. The source
is a soft sphere with radius N/12, center `(N/2,N/2,0.45*N)`, and rate 0.1 per
unit step. The moving source shifts X by `0.05*N*sin(0.5*step)`. Initial density
is zero; initial velocity uses the P1.6 analytical seed.

## Coupled sequence

Each step executes entirely through C++/Metal:

1. RK2/trilinear self-advection of U/V/W from the same old velocity field.
2. Closed outer-wall conditioning and fixed-region velocity rules.
3. Zero-initialized pressure impulse, divergence, geometric V-cycles and gradient
   subtraction; compute the post-projection divergence.
4. Source injection, then RK2 density advection through the projected velocity.
5. Retain density and projected velocity for the next step.

All field buffers and the multigrid hierarchy are allocated once per diagnostic
call and reused across its steps. Commands/settings originate in Python; there
are no Python fluid loops in the native execution path. CPU NumPy loops exist
only in the independent test oracle. Calls export complete fields for validation,
then release all owned GPU buffers. There is no persistent playback session yet.

Cells and timesteps are unit-sized; velocity is voxels per step and pressure is
impulse. Semi-Lagrangian density transport is diffusive and not mass conserving.
`injected_mass` is an independent host calculation of the nominal source sum;
finite precision and transport can change the final mass. The zero-velocity test
checks source integration without transport losses. No temperature, buoyancy,
combustion, collisions, decay or MacCormack correction is included.

## Two different comparisons

With `dense_full=False`, sparse and dense use identical source schedules,
initial fields, masks, boundary conditions and iteration counts. Both enforce
zero pressure outside the prescribed solve region. The sparse path additionally
uses coordinate lookup, absent bricks and canonical face storage. Full-domain
mode 0 also passes the small-grid independent reference, though it allocates all
bricks and offers no sparse-memory advantage.

With `dense_full=True`, the dense engine receives the **same initial velocity
seed and source schedule**, but computes pressure and evolves velocity throughout
the domain. The sparse engine still truncates pressure/transport support to its
fixed region. Pressure is nonlocal; the resulting evolution is not equivalent.
The audit uses eight steps, eight V-cycles and the moving source. This measures
both boundary/support differences and finite-iteration effects, not an isolated
analytical truncation-error estimate.

| Domain | Max velocity error | Max density error | Max divergence error | Absolute total mass difference |
| --- | ---: | ---: | ---: | ---: |
| 64³ | 0.346346 | 0.018643 | 0.000014 | 0.135699 |
| 128³ | 0.423813 | 0.015913 | 0.000228 | 0.354477 |

Predefined unrestricted gates were 1e-4 for maximum velocity and density error.
Both failed. Validation JSON separates `status: PASS` for the implementation
checks from `unrestricted_dense_gate: false` and `milestone_status: OPEN`.
Different solve-region RMS norms must not be compared as if their domains matched;
`divergence_error` compares the exported fields over the whole domain, with sparse
non-solve divergence defined as zero.

## Implementation validation

M5 Pro / Metal, Blender 5.3.0 Alpha `b2e052b7172a`:

- 113 checks passed: both brick sizes, stationary/moving/pulsed sources, full and
  truncated domains, zero velocity, independent coupled NumPy oracle, actual
  missing bricks, density positivity, mass agreement, walls/padding and cleanup.
- Matched native density, velocity, pressure and divergence agree within 1e-6;
  recorded benchmark cases match exactly. Independent CPU gate: 1e-4.
- Three-step independent tests and eight-step native benchmarks exercise retained
  state between steps; invalid settings and budget failure release resources.
- Coupled Blender operator passed. Regressions: multigrid 171, projection 154,
  MAC 96, scalar 55, regions 24, resources 29, standalone 146 and save/load 15.

Run `scripts/coupled_validate.py` in graphical Blender after loading the source
module; run `scripts/coupled_ui_validate.py` with the source add-on registered.
Build with `python3 scripts/build_native.py` using Xcode. Restart Blender after
rebuilding a loaded native binary. Background Blender on this host lacks Metal.

## Measured matched-region cost

Eight steps, eight V-cycles per step, moving source. Times cover completed coupled
GPU work and submission/wait overhead, excluding topology, compilation,
allocation, initialization, source-sum verification and final exports. Sparse runs
first; these are single diagnostic observations, not steady-state playback rates.

| Grid | Brick | Density occupancy | Allocated brick occupancy | Sparse MiB | Dense MiB | Sparse wall ms | Dense wall ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64³ | 8³ | 0.95% | 42.19% | 5.52 | 12.67 | 69.48 | 57.71 |
| 64³ | 16³ | 0.95% | 100.00% | 12.95 | 12.67 | 69.40 | 57.61 |
| 128³ | 8³ | 0.62% | 24.41% | 25.57 | 100.95 | 143.24 | 207.22 |
| 128³ | 16³ | 0.62% | 42.19% | 42.84 | 100.95 | 169.51 | 205.76 |

Density occupancy counts density >1e-6. Allocated occupancy includes all stored
finest bricks and their velocity halo; the pressure solve mask occupies 12.5% of
cells. These small sources do **not** establish the 256³ / approximately 8% smoke
success criterion. Owned memory includes finest velocity/density ping-pong,
pressure/divergence scratch, the coarse hierarchy and lookup/coordinate tables.
The budget applies to each engine's full hierarchy separately; comparison peak
is their sum. CPU and driver allocations are excluded. `topology_ms` records only
finest sparse topology creation, not all setup or dynamic topology updates.

## Next required work

Do not move on to smoke/fire feature ports yet. Pressure support must account for
nonlocal influence instead of treating omitted space as zero pressure by default.
The next correctness experiment should enlarge support or use a conservative
global pressure fallback, then repeat the unrestricted comparison before seeking
memory savings. Dynamic activation must retain velocity and pressure support,
not merely occupied density. Persistent sessions, scene inputs, the larger
occupancy benchmark and comparison with the complete 0.28 reference remain open.

Evidence and source/binary hashes: [validation/native_p18](validation/native_p18).

## Follow-up in 0.38

The [global-coverage fallback](GLOBAL_COVERAGE.md) resolves this native accuracy
mismatch by allocating all bricks. It does not resolve sparse efficiency. The
0.37 results above remain the historical restricted-support baseline.
