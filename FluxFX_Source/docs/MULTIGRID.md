# Version 0.10 — dense multigrid pressure optimization

The P0.9 benchmark identified pressure as the principal 128³ bottleneck.
Version 0.10 retains Jacobi and adds a geometric multigrid V-cycle solver through
Blender's existing GPU API. No sparse bricks, native C++, or dependency changes.

## Measured outcome

Apple M5 Pro / Metal, Blender 5.3.0 Alpha b2e052b7172a, September 21, 2026.

| Matched-input pressure solve | Jacobi median | Multigrid median |
| --- | ---: | ---: |
| 64³ | 2.541 ms | 3.863 ms |
| 128³ | 66.355 ms | 11.218 ms |

The 128³ snapshot solve is **5.9× faster**, with better measured convergence.
For the first solve on identical 128³ velocity fields, the RMS divergence ratio
fell from 0.04540 (Jacobi) to 0.002202 (multigrid), meaning 95.46% versus 99.78%
reduction. Both methods improved further over repeated solves of that snapshot.
At 64³, Jacobi remains faster on a steady warm start, so **Auto keeps Jacobi there**.

| Complete simulation step | P0.9 Jacobi | 0.10 Auto |
| --- | ---: | ---: |
| 64³ fixed median | 3.864 ms | 3.884 ms |
| 64³ adaptive median | 4.933 ms | 5.001 ms |
| 128³ fixed median | 73.462 ms | 19.801 ms |
| 128³ adaptive median | 75.502 ms | 21.780 ms |
| 128³ adaptive p95 | 269.607 ms | 22.495 ms |

The fixed 128³ step is about **3.7× faster** and adaptive about **3.5× faster**.
The latter no longer pays the old 1280-fine-pass cold-solve cost when dt changes.
These are separate single-session benchmark runs, not controlled independent
trials or viewport FPS. Timings include synchronization/readback overhead.
The matched-input pressure comparison uses 10 warm samples per method; complete
step measurements use the P0.9 harness with 30 samples. Full-flow trajectories
change with better projection and adaptive dt, so their workloads are not identical.

## Selection and controls

**Pressure solver** in the setup section offers Auto, Jacobi, and Multigrid.
Auto chooses multigrid for coarsenable grids with maximum dimension at least 128;
it retains Jacobi for smaller grids. The UI's cubic 16/32/64/128 grids all support
multigrid. Manual Multigrid is useful at 64³ when lower divergence matters more
than the small timing increase. Solver choice requires rebuilding the simulation.

**Multigrid cycles**, in Flow, is live-editable from 1 to 16, default four.
The original Jacobi iteration budget remains available when that method is selected.
Divergence reports identify the method, cycle count, hierarchy, and summed smoothing
passes. Summed passes across different grid sizes must not be compared as equal
work to full-resolution Jacobi iterations. UI measurements show V-cycles directly.

## Numerical method

Each V-cycle uses three weighted-Jacobi pre-smoothing passes, computes the
Neumann residual `rhs - Lp`, averages 2×2×2 residual blocks onto the coarse grid,
and solves for a zero-initialized coarse correction. Trilinear interpolation
adds that correction to the fine pressure, followed by three post-smoothing
passes. The coarsest grid uses 80 weighted-Jacobi passes. Relaxation is fixed at
2/3 for multigrid smoothing. Fine pressure is warm-started at unchanged dt; a dt
change clears the fine guess. Four cycles are used for both cold and warm solves.

The finest RHS is divergence/dt; restricted residual RHS values are already in
pressure-equation units and use dt=1 in recursive smoothers. Grid spacing follows
the fixed physical domain at every level. Exterior neighbours are omitted in
the Laplacian, and correction interpolation uses clamped Neumann extension.
The pressure constant nullspace is harmless to gradients; no absolute-pressure
interpretation is intended. Floating-point mean residual can limit convergence.

Coarsening halves every dimension only while all are even and the smallest is
at least eight. A 128³ hierarchy ends at 4³. Shapes with no valid coarse level
fall back to Jacobi. Coarse domains with extreme aspect ratios are not claimed
to converge well; the tested non-cubic geometry is modest. This is a fixed-budget
solver, not a residual-tolerance solver or an automatic quality guarantee.

For background, [Bridson et al.'s multigrid discussion](https://www.cs.ubc.ca/~rbridson/docs/zhang-siggraph2016-whirp_vflip.pdf)
describes cell aggregation and coarse correction in fluid solves. This implementation
uses a simpler uniform-domain rediscretization with trilinear correction, not
that paper's adaptive boundary-layer method.

## Ownership and memory

The projector subclass shares wall handling, divergence, gradient correction,
and diagnostics with the Jacobi baseline. The pressure solve is an overridable
method; the numerical backend remains independent of Blender UI. Coarse textures
are owned by the projector and released on reset/rebuild/disable through the
existing lifecycle. Reset clears coarse corrections as well as the fine pressure.

At 128³, extra multigrid fields occupy 13,181,952 bytes, about 12.57 MiB. Total
Auto-mode field storage including adaptive scratch is about 157.844 MiB, versus
145.272 MiB for Jacobi. Driver/shader/viewport overhead is excluded. No extra
CPU readbacks occur during V-cycles; adaptive timestep reads remain unchanged.

## Verification

- 58 standalone tests pass, including hierarchy selection, automatic/manual
  policy, invalid cycle budgets, and live versus reset-required settings.
- Seven GPU operator/lifecycle checks validate residuals against an independent
  CPU Neumann Laplacian, restriction, constant/linear prolongation and boundary
  extension, zero flow, random signed flow, walls/divergence, dt-change/reset,
  and live cycle updates (some checks cover several related invariants).
- Seven integration cases cover manufactured gradients on 8³, 16×8×8, and odd
  9×7×5 fallback grids, plus 30-step fixed/adaptive runs at 64³ and 128³.
  Matched-input comparisons additionally require lower first/last divergence
  ratios than Jacobi at both benchmark resolutions.
- All six original pressure GPU cases pass after the default policy changes.
- All 17 UI/lifecycle checks pass, including Auto at 128³, live cycle changes,
  switching back to Jacobi, and release of multigrid resources.

[Matched-input and coupled results](validation/m5-pro-multigrid-010.json) ·
[Operator checks](validation/m5-pro-multigrid-operators-010.json) ·
[Pressure regression](validation/m5-pro-pressure-010.json) ·
[UI checks](validation/m5-pro-ui-010.json) ·
[Full benchmark](validation/m5-pro-benchmark-010.json).

Run the two `scripts/multigrid*_validate.py` scripts through `runpy` with
`run_name='__main__'` after loading the source add-on in graphical Blender.
The benchmark and earlier pressure suite remain available for comparisons.

## Next priorities

With pressure improved, profile the remaining velocity/scalar transport and
adaptive synchronization costs before making further speed claims. Longer-run
quality tests, tolerance-based stopping, strongly anisotropic domains, and
scene-integrated rendering remain open work. This update does not add combustion,
mesh collisions, caching, or sparse simulation.
