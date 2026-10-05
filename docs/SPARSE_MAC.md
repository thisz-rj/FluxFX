# P1.5 — Sparse MAC velocity (0.34.0)

P1.5 adds native Metal transport of staggered U/V/W velocity, with numerical
comparisons against native dense, independent NumPy, and existing Blender dense
shader implementations. The interactive smoke preview remains the dense engine.
The next stage is **P1.6: sparse divergence and a verified Jacobi pressure solve**.

## Run

Install `fluxfx-0.34.0.zip` in Blender 5.3 on Apple Silicon. Open the FluxFX sidebar,
then **Native core · P1.5 → Compare Sparse Velocity**. This runs 64³, 8³ bricks,
three steps and a localized affine field. `FluxFX Sparse MAC.json` contains the
result. The UI's native memory budget is applied to each engine separately.

Build from source with `python3 scripts/build_native.py` using Xcode. Restart
Blender after rebuilding a loaded native binary. Metal tests need a graphical
Blender process; background mode on this machine does not expose a Metal device.
Python sends settings and reads diagnostic results; all native field initialization,
transport loops, dispatch and comparison execute in C++/Metal.

```python
from fluxfx.native import compare_mac
report = compare_mac(resolution=128, side=8, steps=3, mode=0,
                     budget_bytes=256 * 2**20)
faces = report.pop("faces")  # float32 bytes, diagnostic readback only
print(report)
```

Supported resolution: 32/64/128; brick side: 8/16; steps: 0–8. Modes are localized
affine (0), full-domain affine (1), full-domain constant (2), localized signed box
(3). Velocities are voxels per step; the test uses unit cell size and timestep.
This API creates, tests and releases temporary engines; it is not a persistent
simulation API. `faces` concatenates U, V, W, each x-fastest with shapes
`(N+1,N,N)`, `(N,N+1,N)`, `(N,N,N+1)` respectively in x/y/z order.

## Face ownership and transport

An interior interface face belongs to the positive-side brick's lower plane.
At the global positive domain boundary the last brick owns its upper plane.
Each component reserves `(side+1)*side*side` floats per brick, oriented along
that component. Interior upper planes are unused padding. Tests initialize these
planes with a sentinel and verify they remain untouched. Sampling always resolves
the canonical owner through the coordinate-to-brick map.

Each GPU step traces backward using midpoint RK2 and trilinear interpolation of
all three staggered components. U/V/W dispatches read the same old field; the two
field buffers swap after all three dispatches finish. Missing bricks sample zero.
Domain-edge sampling clamps to the last face (constant extrapolation), matching
the existing transport shader. These are transport boundaries, not solid walls;
pressure projection is absent.

Localized modes preallocate a fixed brick box around the initial central half-width
field, expanded by `2*steps+2` cells. This conservative support is for these bounded
test velocities (component magnitudes below 0.55). It does not establish safe
activation for arbitrary flows. Full-domain modes test global edges and exact
canonical face counts. Dynamic activation, retained velocity support and coupling
to sparse density remain subsequent integration work.

## Measured results

Apple M5 Pro, Metal, Blender 5.3.0 Alpha `b2e052b7172a`, Python 3.13.13.
Recorded native test results: localized affine mode, three complete U/V/W steps.
Wall times include submission and completion waits, exclude setup/compilation,
initialization, topology construction and final readback. These are short runs,
not steady-state performance guarantees; per-step GPU times and topology time
are preserved in the JSON evidence.

| Grid | Brick | Sparse MiB | Dense MiB | Sparse wall ms | Dense wall ms |
| --- | --- | ---: | ---: | ---: | ---: |
| 64³ | 8³ | 2.85 | 6.09 | 7.61 | 2.65 |
| 64³ | 16³ | 6.38 | 6.09 | 11.59 | 3.84 |
| 128³ | 8³ | 13.21 | 48.38 | 16.55 | 9.11 |
| 128³ | 16³ | 21.52 | 48.38 | 15.93 | 8.59 |

The 128³/8³ case reduces owned GPU memory by about 73%, but sparse velocity
transport is slower in these measurements. At 64³/16³ the conservative allocation
also costs more memory than dense. No velocity speedup is claimed. Scalar P1.4
speedups must not be extrapolated to MAC transport or a complete smoke engine.

Memory includes two velocity field sets, coordinate map, brick coordinates and
alignment. Driver/pipeline memory and CPU topology/readback are excluded. Each
engine enforces its own owned-buffer budget; the comparison's simultaneous GPU
peak is the sum of both engines. Allocation failures and normal completion release
all owned MAC buffers. The budget is not a total process-memory limit.

## Validation

Run `scripts/sparse_mac_validate.py` in graphical Blender after loading the source
module. It writes `test-results/sparse-mac-validation.json`. The historical
`scripts/mac_validate.py` remains the P0.3 dense suite. Run
`scripts/sparse_mac_ui_validate.py` with the source add-on registered to test the
operator and report. Tests read back full fields explicitly; this is not a playback
implementation.

- 96 MAC checks passed: both brick sizes, all four modes, zero/three steps,
  signed/nonuniform fields, sparse holes, boundaries, constant preservation,
  canonical ownership, untouched padding, invalid parameters, budgets and cleanup.
- Native sparse and dense results matched exactly in all recorded cases.
- Independent NumPy reference passed the 1e-4 tolerance.
- Existing Blender dense shader maximum difference: 2.2351741790771484e-7.
- UI diagnostic passed; no owned MAC buffers remained afterward.
- Regressions passed: scalar transport 55, regions 24, resources 29,
  standalone tests 146, registration/save/load 15.

Evidence and source/binary hashes are in [validation/native_p15](validation/native_p15).
The result establishes cross-brick velocity transport correctness for these tests.
It does not yet establish incompressible sparse smoke, realtime performance,
pressure behavior, dynamic topology correctness, or P1.8 full-engine equivalence.
