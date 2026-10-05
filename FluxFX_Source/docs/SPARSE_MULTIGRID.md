# P1.7 — Sparse geometric multigrid (0.36.0)

P1.7 adds native Metal geometric V-cycles to the P1.6 fixed-region pressure
baseline. Sparse and dense multigrid outputs match exactly in the recorded
cases; 171 numerical checks passed. Interactive smoke still uses the dense engine.
This stage validates a sparse pressure hierarchy on prescribed aligned regions,
not dynamic topology or complete sparse smoke equivalence.

## Run

Install `fluxfx-0.36.0.zip` in Blender 5.3 on Apple Silicon. Choose
**Native core · P1.7 → Compare Sparse Multigrid** in the FluxFX sidebar.
The 64³ diagnostic uses four V-cycles and 8³ bricks and writes
`FluxFX Sparse Multigrid.json`. The native memory setting limits the full
hierarchy plus finest-level fields per engine; the two-engine comparison may
simultaneously own twice that limit.

```python
from fluxfx.native import compare_multigrid
report = compare_multigrid(resolution=128, side=8, cycles=8, mode=1,
                          budget_bytes=256 * 2**20)
for key in ('faces', 'pressure', 'before', 'after'):
    report.pop(key)  # full-field diagnostic exports
print(report)
```

Supported grids: 32/64/128. Brick sides: 8/16, shrinking to the grid size on
small coarse levels. Cycles: 1–16. Modes and float32 export layouts are inherited
from [P1.6](SPARSE_PRESSURE.md): full domain, centered cube, disconnected cubes,
zero flow and a manufactured gradient field. The Jacobi API remains available.

Build with `python3 scripts/build_native.py` using Xcode, then restart Blender
if it already loaded the native binary. Run GPU tests in graphical Blender;
background mode on this M5 Pro does not expose Metal. Python sends commands;
C++ builds the hierarchy and Metal executes all numerical passes. CPU field
readback is confined to diagnostics.

## Hierarchy and V-cycle

The solver halves resolution down to 8³ (3/4/5 levels for 32/64/128). Each
coarse sparse level has its own coordinate lookup, active brick coordinates,
pressure ping-pong, RHS and residual scratch. Only bricks intersecting the solve
mask are allocated on coarse levels. No coarse velocity arrays are allocated.
The finest level retains P1.6's conservative velocity-owner halo. At small
coarse grids the brick allocation may cover the whole grid.

Each V-cycle performs:

1. Four weighted-Jacobi pre-smoothing passes, relaxation 2/3.
2. Residual evaluation with the current six-neighbor pressure operator.
3. Eight-child average restriction, multiplied by four for doubled cell spacing.
4. Recursive coarse correction from zero; the 8³ level uses 128 smoothing passes.
5. Cell-centered trilinear prolongation and additive correction.
6. Four post-smoothing passes.

The coarse operator is rediscretized, not Galerkin. At physical outer walls,
pressure has the same Neumann rule as P1.6; prolongation clamps exterior samples.
At an interior truncated solve boundary, omitted pressure remains zero and still
contributes to the diagonal. The prescribed masks align under the supported
coarsenings, including disconnected cubes. Transfers are not validated for
arbitrary cut cells, thin features, moving obstacles or merging components.

Separate compute encoders and tracked buffers order dependent passes; coarse
pressure is cleared with a blit encoder before each recursive solve. Hierarchy
memory is included in the hard owned-buffer budget. Partially constructed
hierarchies release their allocations on failure. Driver/pipeline and CPU memory
are outside that budget. There is no persistent hierarchy reuse, convergence
stopping criterion, explicit pressure gauge pin, or exact coarse solve yet.

## Correctness

On Apple M5 Pro / Metal, Blender 5.3.0 Alpha `b2e052b7172a`:

- 171 checks passed, covering independent NumPy V-cycles, sparse/dense equality,
  both brick sizes, all five modes, real missing bricks, padding, walls, zero
  preservation, convergence histories, parameter errors and allocation cleanup.
- Native dense/sparse pressure and projected faces matched exactly.
- Independent-reference maximum-error gate: 5e-5.
- Pressure residual and projected divergence RMS agree within 1e-6.
- Four-cycle tests at 32³ reduce divergence by more than 90%; larger tests
  use an eight-cycle gate. Increasing cycles reduced residual in every recorded
  64³/128³ centered-region sequence.
- Blender UI passed; prior projection 154, MAC 96, scalar transport 55, regions
  24, resources 29, standalone tests 146 and save/load 15 all passed again.

The projection regression retains the full-domain comparison against Blender's
existing pressure shaders. The multigrid CPU oracle shares only field initialization
and layout helpers with it; its smoothing and transfer operations are independent
NumPy implementations.

## Convergence and memory

Centered solve cube: 12.5% solve-cell occupancy. Memory includes the finest fields,
velocity halo, coarse scalar hierarchy, lookup tables, coordinates and alignment.
It excludes CPU/driver memory. Dense uses the identical solve mask; it does not
solve pressure throughout the exterior region.

| Domain | V-cycles | Levels | RMS divergence reduction | Sparse MiB | Dense MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 64³ | 1 | 4 | 83.17% | 4.67 | 10.67 |
| 64³ | 2 | 4 | 95.57% | 4.67 | 10.67 |
| 64³ | 4 | 4 | 98.59% | 4.67 | 10.67 |
| 64³ | 8 | 4 | 99.84% | 4.67 | 10.67 |
| 128³ | 1 | 5 | 69.78% | 21.66 | 84.95 |
| 128³ | 2 | 5 | 85.39% | 21.66 | 84.95 |
| 128³ | 4 | 5 | 89.01% | 21.66 | 84.95 |
| 128³ | 8 | 5 | 93.42% | 21.66 | 84.95 |

Convergence is weaker at 128³ than at 32³, particularly near the truncated
boundary. This baseline is not resolution-independent or fully converged. The
remaining pressure error must be considered when integrating the engine.

## Common-target timing

`scripts/sparse_multigrid_benchmark.py` uses a target residual/divergence ratio
<=0.1, the same 128³ region and 8³ bricks. A bounded Jacobi search tries
128/256/512/1024 iterations: 1024 is the first tested count that passes. Eight
V-cycles also pass. This is a shared threshold, not identical final residuals or
an exact minimum-iteration search.

Three repeated runs, alternating which solver runs first, measured median sparse
completed projection wall time of **15.50 ms multigrid versus 96.62 ms Jacobi**,
about **6.2× faster** for this diagnostic. Timings include divergence, solve,
gradient subtraction, final divergence and completion wait. They exclude hierarchy
construction, shader compilation, allocation, initialization and CPU exports.
Each call creates fresh temporary engines. Sparse runs before dense inside each
call; there is no steady-state or full smoke performance claim. All raw timing
samples and achieved residuals are archived.

Scripts: `sparse_multigrid_validate.py`, `sparse_multigrid_benchmark.py`, and
`sparse_multigrid_ui_validate.py` in `scripts/`. Evidence and source/binary hashes
are in [validation/native_p17](validation/native_p17).

## Remaining integration

Zero-pressure truncation remains a modeling approximation: pressure is nonlocal,
and these results do not prove equivalence to unrestricted dense smoke. Dynamic
pressure support, arbitrary evolving fields, persistent sessions and coupling
scalar transport to projected velocity are pending. P1.8 should integrate these
pieces and compare matched source schedules, density, velocity, divergence, mass,
timing and memory before porting the remaining smoke/fire features.
