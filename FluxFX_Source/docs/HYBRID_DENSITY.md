# P1.8 hybrid density — 0.39.0

The global brick fallback in 0.38 restored accuracy but cost more than dense.
This diagnostic stores global velocity, pressure and multigrid levels in dense
arrays, while density has its own brick map, coordinates and two buffers.
Density injection and transport dispatch only over those allocated cells.
Velocity sampling during density advection uses the independent dense MAC
layout; density interpolation uses the sparse map with zero for missing cells.
All fluid updates remain native Metal. Python invokes and reports diagnostics.

The density region is the central half of the domain plus one brick on each
side, clipped to the domain. It is fixed throughout each call. It is not inferred
from smoke occupancy or guaranteed conservative for arbitrary flows. There is
no online support-loss detector or automatic expansion yet. The comparison
against unrestricted dense detects numerical discrepancies in the tested runs;
this API must not be used as a general adaptive simulation.

## Evidence on M5 Pro

Graphical Blender 5.3.0 Alpha `b2e052b7172a`, Python 3.13.13, native Metal.
209 checks pass: 32³ independent NumPy reference cases; 8³/16³ brick layouts;
static, moving and intermittent emission; localized, disconnected and zero
initial velocity. Additional dense comparisons exercise full analytic and
manufactured-gradient seeds at 64³ and 128³ with 1, 4 and 16 steps. Native
comparison tolerance is 1e-6, CPU tolerance 1e-4, and mass agreement 1e-5.
Eight-step benchmarks measured zero difference in density, velocity, pressure
and divergence. Invalid inputs, budget rejection, walls, padding and owned
buffer cleanup also pass. Small domains may allocate every density brick.

| 128³ case | Density bricks | Density cell coverage | Density allocation MiB | Total owned MiB | GPU ms / eight steps |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hybrid 8³ | 1000 | 24.41% | 3.933 | 88.951 | 278.90 |
| Paired dense reference | — | 100% | 16.000 | 100.948 | 290.44 |
| Hybrid 16³ | 216 | 42.19% | 6.755 | 91.710 | 281.76 |
| Paired dense reference | — | 100% | 16.000 | 100.948 | 288.54 |

Timing values are medians of five paired samples after one warmup for each
brick size, eight steps and eight V-cycles per step. Hybrid runs before dense
in each pair; order/thermal bias is possible. The measured reductions are about
4.0% and 2.3%, not a broad performance guarantee. Density remains a small part
of the total cost: global velocity transport and pressure still process the
whole domain. Density occupancy in this benchmark is only about 0.61%, not
the planned 8% smoke occupancy. The 256³ headline benchmark is still pending.

GPU timings exclude initialization, compilation, readback and host comparisons.
They are not viewport FPS. Total owned memory includes fields, hierarchy and
maps, but not driver allocations. Both engines coexist during comparison, so
peak comparison memory is their sum. `density_bytes` includes both density
buffers and its additional map/coordinates in hybrid mode. `density_cells` and
`density_bricks` describe density allocation; the legacy `active_bricks` field
still describes global pressure support. `density_topology_ms` measures fixed
density map construction separately from the pressure `topology_ms` field.

Regression suites pass: global coverage 115, coupled 113, multigrid 171,
projection 154, MAC 96, scalar transport 55, regions 24, resources 29,
standalone Python 146, Blender save/load 15, and the new UI report/cleanup test.
[Archived reports and source/binary hashes](validation/native_p18_hybrid)
include all results and each timing sample.

## Reproduce

Build with `python3 scripts/build_native.py` using the Apple Silicon Xcode
setup, then package with `python3 scripts/package.py`. Install
`fluxfx-0.39.0.zip` in Blender 5.3 Apple Silicon. Restart Blender when replacing
an already-loaded native module. Choose **Native core · P1.8 → Compare Hybrid
Density**; the default 64³ result is **FluxFX Hybrid Density.json** in the Text
Editor. Interactive smoke continues to use the established dense solver.

`fluxfx.native.compare_hybrid_coupled` accepts the same seed, schedule, step,
cycle and budget settings as the global comparison. Run
`scripts/hybrid_validate.py`, `scripts/hybrid_ui_validate.py` (registered addon)
and `scripts/hybrid_timing.py` in graphical Blender with the repository on
Python's import path. Reports go into `test-results`. Background Blender can
check registration/save/load but cannot run Metal tests in this environment.
No additional Blender API limitation was encountered.

## Remaining gate

This is a bounded native storage/dispatch milestone. It does not establish
persistent or adaptive simulation, full sparse pressure, arbitrary sources,
or dense 0.28 feature parity. The UI deliberately keeps
`sparse_efficiency_gate=false`: the full P1.8 gate is still open.

Next: detect approaching density-support boundaries, expand/remap density
bricks without losing values, and validate those transitions against this
unrestricted reference. Keep pressure and velocity global while establishing
adaptive scalar correctness. Thermal/fire/liquid feature ports remain deferred.

## Follow-up in 0.40

[Adaptive density growth](ADAPTIVE_DENSITY.md) adds conservative GPU support
detection and append-only brick expansion. It preserves tested density through
transitions, but its full-domain scan and transient copies need optimization.
