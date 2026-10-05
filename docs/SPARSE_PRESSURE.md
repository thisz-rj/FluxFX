# P1.6 — Sparse divergence and Jacobi projection (0.35.0)

The native Metal diagnostic now computes divergence, solves a pressure impulse
and subtracts its gradient from staggered velocity. All 154 projection checks
passed. This is a fixed-region numerical baseline, not yet an integrated sparse
smoke engine. The interactive smoke preview still runs the dense reference.

## Run and build

Install `fluxfx-0.35.0.zip` in Blender 5.3 on Apple Silicon. In the FluxFX sidebar,
choose **Native core · P1.6 → Compare Sparse Pressure**. The fixed 64³ diagnostic
uses 8³ bricks, 128 iterations and a centered solve region; its report appears in
`FluxFX Sparse Pressure.json`. The native memory budget applies to each engine.

Build with `python3 scripts/build_native.py` using Xcode. Restart Blender after
rebuilding a loaded native module. Graphical Blender is required on this M5 Pro
host; background mode does not expose Metal. Run
`scripts/sparse_projection_validate.py` for numerical validation, and
`scripts/sparse_projection_ui_validate.py` with the source add-on registered for
the operator test. Reports go to `test-results/`.

```python
from fluxfx.native import compare_projection
report = compare_projection(resolution=128, side=8, iterations=128, mode=1,
                            budget_bytes=256 * 2**20)
for name in ('faces', 'pressure', 'before', 'after'):
    report.pop(name)  # full-field float32 diagnostic exports
print(report)
```

Resolution is 32/64/128, brick side 8/16, iterations 0–1024. Modes: full domain
with analytic velocity (0), centered half-width cube (1), two disconnected
quarter-width cubes (2), full-domain zero flow (3), and full-domain manufactured
pressure-gradient velocity (4). These masks are prescribed tests, not smoke-density
thresholds or scene colliders. Python submits settings; native C++/Metal performs
the solve, dispatch loops and diagnostic reductions/readback.

## Discretization and boundaries

Unit cell spacing is used. Stored pressure is impulse `q = dt*p`, so the system
is `L(q) = divergence(u)` and projection is `u_new = u - gradient(q)`.
The six-neighbor Jacobi update uses relaxation 2/3, zero initial pressure and a
fixed iteration count. Each iteration has a separate Metal compute encoder to
order tracked-buffer reads and writes. There is no convergence-based early stop.

At the outer domain walls, normal velocity is zero and exterior neighbors are
omitted from the pressure diagonal and sum (homogeneous Neumann condition).
The full-domain RHS comes from wall-conditioned face velocities and is compatible
with the constant-pressure nullspace up to floating-point roundoff. Pressure has
no explicit gauge pin; zero initialization fixes the starting guess. These short
diagnostics do not establish long-run drift behavior.

At an interior boundary of a sparse solve region, exterior pressure is explicitly
zero (Dirichlet condition); the neighbor still contributes to the diagonal.
This is a **truncated pressure-domain boundary**, not a solid wall or a validated
smoke free surface. Normal velocity can cross it. Pressure is zero in non-solve
cells, and faces with neither adjacent cell in the solve region remain zero.
Divergence and residual norms include solve cells only; exported divergence is
zero elsewhere. No incompressibility claim is made outside that region.

The dense comparison uses exactly the same solve mask and boundary conditions.
It proves storage and dispatch equivalence for that problem. It does not show
that truncating pressure support reproduces an unrestricted full-domain smoke
solve: pressure influence is nonlocal. Full-domain mode is separately compared
against Blender's existing dense pressure shaders.

Velocity uses the canonical face ownership from P1.5: positive-side brick owns
an internal face, final brick owns the global upper face. A conservative brick
halo retains every solve face's owner, including positive-side exterior faces.
Unused upper-plane padding is sentinel-checked. This version allocates scalar
scratch for halo bricks too and dispatches over them, zeroing non-solve cells.
Dynamic pressure support and topology changes are deferred.

## Validation and measurements

Host: Apple M5 Pro, Metal, Blender 5.3.0 Alpha `b2e052b7172a`, Python 3.13.13.

- 154 projection checks passed: native dense equality, independent NumPy oracle,
  both brick sizes, full/partial/disconnected solve regions, actual missing bricks,
  zero flow, manufactured gradient removal, closed-wall compatibility, energy
  non-increase, padding, invalid parameters, budget failures and cleanup.
- Native sparse pressure and velocity matched dense exactly in recorded cases.
- Independent reference gate: maximum absolute error <=2e-5.
- Blender full-domain projected-velocity maximum error: 4.76837158203125e-7.
- Independently computed pressure residual RMS matches post-projection divergence
  RMS within 1e-6; increasing iterations lowers residual in the checked case.
- UI passed; standalone tests 146, save/load checks 15, MAC 96, scalar transport
  55, active regions 24 and resource layer 29 passed.

The following short-run measurements use mode 1, 128 Jacobi iterations, solve-cell
occupancy 12.5%, and include halo allocations. They time divergence, all iterations,
gradient subtraction and final divergence, including submission/completion waits.
They exclude topology construction, shader compilation, allocation/initialization
and CPU export/comparison. Sparse runs first. These are diagnostic observations,
not steady-state or complete smoke performance claims.

| Domain | Brick | Allocated bricks | Sparse MiB | Dense MiB | Sparse wall ms | Dense wall ms | RMS divergence reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64³ | 8³ | 216 | 4.54 | 10.09 | 3.29 | 6.99 | 86.9% |
| 64³ | 16³ | 64 | 10.38 | 10.09 | 6.20 | 4.83 | 86.9% |
| 128³ | 8³ | 1000 | 21.02 | 80.38 | 15.54 | 22.19 | 55.4% |
| 128³ | 16³ | 216 | 35.02 | 80.38 | 16.27 | 21.87 | 55.4% |

At 128³, 128 iterations leave about 45% of the initial RMS divergence. Jacobi is
an approximate baseline, not a converged production solve. P1.7 sparse multigrid
should target faster convergence with residual-based comparisons.

Owned GPU memory includes two velocity sets, pressure ping-pong, two divergence
fields, coordinate lookup, brick coordinates and alignment. The per-engine budget
excludes CPU topology/export, driver/pipeline allocations and other Blender memory;
the simultaneous comparison peak is the sum of sparse and dense columns. All owned
projection buffers are released before return, including failure after the first
engine is created. Float32 exports use x-fastest order: pressure/before/after are
N³; faces concatenate U `(N+1,N,N)`, V `(N,N+1,N)`, W `(N,N,N+1)` in x/y/z.

Evidence and source/binary hashes: [validation/native_p16](validation/native_p16).
Anisotropic cells, arbitrary input fields, persistent sessions, dynamic pressure
support, colliders, source coupling, multigrid and full-engine equivalence remain
outside this stage. The next milestone is P1.7, followed by P1.8 matched full-engine
validation before adding the remaining smoke/fire features.
