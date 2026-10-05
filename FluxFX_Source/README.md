# FluxFX — P1.8 density capacity (package 0.41)

A working dense GPU temperature, buoyancy, and pressure-projection prototype for **Blender 5.3**, targeting
**Apple Silicon / Metal first**. Python coordinates passes; GLSL kernels evolve
the density on the GPU. The package includes an Apple Silicon native diagnostic module; source builds require Xcode. Static-collider coarse solves use NumPy bundled with Blender.

Tested on Apple M5 Pro / Metal, Blender **5.3.0 Alpha**, build **b2e052b7172a**
(2026-09-20). The writable R32F 3D texture probe and 64³ / 128³ advection tests
passed. See [0.20 collider speed and detail](docs/COLLIDER_DETAIL.md), [0.19 static collisions](docs/COLLIDERS.md), [0.18 wall-clock playback](docs/PLAYBACK.md), [0.17 motion and speed](docs/MOTION_DETAIL.md), [0.16 smoke detail](docs/SMOKE_DETAIL.md), [0.15 native comparison](docs/NATIVE_COMPARISON.md), [0.14 multiple emitters](docs/MULTIPLE_EMITTERS.md), [0.13 emitter motion](docs/EMITTER_MOTION.md), [0.12 object emitters](docs/OBJECT_EMITTERS.md), [0.11 scene domain](docs/SCENE_DOMAIN.md), [0.10 multigrid optimization](docs/MULTIGRID.md), [P0.9 benchmarks](docs/P0_9.md), [P0.8 adaptive steps](docs/P0_8.md), [P0.7 volume preview](docs/P0_7.md), [P0.6 live controls](docs/P0_6.md), [P0.5 results](docs/P0_5.md), [P0.4 results](docs/P0_4.md), [P0.3 results](docs/P0_3.md) and [baseline validation](docs/VALIDATION.md) for measurements and limits.

**0.41 gives density its own capacity-managed GPU buffer.** Choose
**Native core · P1.8 → Compare Density Capacity**. All 237 checks passed.
At 128³/8³, measured peak buffer memory drops from 166.29 to 85.85 MiB;
eight-step wall time improves from about 352 to 303 ms in three timed samples.
Dense is still slightly faster. See [capacity design and limits](docs/DENSITY_CAPACITY.md).

**0.40 detects missing density support and grows bricks safely.** Choose
**Native core · P1.8 → Compare Adaptive Density**. All 231 adaptive checks passed,
including repeated growth, byte-for-byte preservation and dense-reference
agreement. This correctness baseline scans the full domain and temporarily
copies the main buffer when growing; peak memory and completed-step time are
worse than dense. P1.8 remains open. See [adaptive growth and limits](docs/ADAPTIVE_DENSITY.md).

**0.39 separates sparse density from global pressure and velocity.** Choose
**Native core · P1.8 → Compare Hybrid Density**. All 209 validation checks passed.
At 128³ with 8³ bricks, the tested hybrid uses 88.95 MiB versus 100.95 MiB dense,
and five timed samples measured a roughly 4% GPU-time reduction. This remains
a fixed-support diagnostic, not adaptive sparse smoke. P1.8 stays open.
See [hybrid implementation, measurements and limits](docs/HYBRID_DENSITY.md).

**0.38 adds a conservative global-coverage fallback.** Choose **Native core ·
P1.8 → Compare Global Coverage**. All 115 checks passed, including unrestricted
native dense equivalence at 64³ and 128³. This allocates every brick: it uses
more memory and runs slower than dense. **P1.8 remains open for sparse efficiency
and full reference-physics validation.** Interactive smoke still uses the dense
solver. See [coverage correction, evidence and limits](docs/GLOBAL_COVERAGE.md).

**0.37 begins P1.8 with a coupled native engine and a dense-equivalence audit.**
Choose **Native core · P1.8 → Compare Coupled Engine** for matched-region checks.
Velocity transport, multigrid projection, source injection and density transport
now run together over multiple steps. All 113 implementation checks passed, but
**unrestricted dense equivalence failed** because the sparse pressure region
changes the flow. P1.8 remains open; interactive smoke still uses the dense solver.
See [results, reproducible audit and required next work](docs/COUPLED_VALIDATION.md).

**P1.7 adds sparse geometric multigrid**, packaged as 0.36.0. Choose
**Native core · P1.8 → Compare Sparse Multigrid**. All 171 numerical checks passed.
At 128³, eight V-cycles reduced divergence by about 93%; the common-target
benchmark measured 15.5 ms versus 96.6 ms for Jacobi. This is a fixed-region
pressure diagnostic, not full smoke performance. See
[hierarchy, convergence, timings and limitations](docs/SPARSE_MULTIGRID.md).

**P1.6 adds sparse divergence and Jacobi pressure projection**, packaged as
0.35.0. Choose **Native core · P1.8 → Compare Sparse Pressure**; the report is
`FluxFX Sparse Pressure.json`. All 154 numerical checks passed. Sparse and dense
results match with identical solve regions and boundary rules. The 128³ test
reduces divergence by about 55% after 128 iterations; it is not fully converged.
See [boundaries, validation and measurements](docs/SPARSE_PRESSURE.md). The sparse
paths remain fixed-region diagnostics; interactive smoke still uses the dense solver.

**P1.5 adds native sparse U/V/W velocity self-advection**, packaged as 0.34.0.
Choose **Native core · P1.8 → Compare Sparse Velocity** for a fixed 64³ test.
The report is `FluxFX Sparse MAC.json`. All 96 numerical checks passed, including
brick-face ownership, interpolation and comparison with Blender's dense shader.
At 128³, 8³ bricks used 13.21 MiB versus 48.38 MiB for dense velocity buffers,
but sparse advection was slower in this run. This is a fixed-topology diagnostic;
coupling into the interactive sparse smoke solver is still pending; P1.6 adds a separate pressure diagnostic.
See [implementation, measured tradeoffs and validation](docs/SPARSE_MAC.md).

**P1.4 adds native sparse density advection and a dense comparison**, packaged
as 0.33.0. Choose **Native core · P1.8 → Compare Sparse Density** for the fixed
128³ benchmark. Results appear in `FluxFX Sparse Transport.json`; the Image
Editor gets `FluxFX Sparse Density`. Numerical checks passed against native dense,
an independent reference and the existing Blender dense transport shader. See
[method, measured memory/timing and limits](docs/SPARSE_TRANSPORT.md).

**P1.3 adds source-driven active regions and a visible brick preview**, packaged
as 0.32.0. Create a domain/emitter, then choose **Native core · P1.8 → Show Active
Bricks**. Cyan marks required bricks; orange marks temporarily retained bricks.
Move emitters to inspect activation, velocity coverage and delayed removal.
See [setup, controls and limitations](docs/ACTIVE_REGIONS.md). The interactive smoke solver is still the dense reference.

**P1.2 adds a preallocated sparse brick pool**, packaged as 0.31.0. Open
**Native core · P1.8 → Test Sparse Brick Pool** to check both 8³ and 16³ bricks.
Native code manages active/free slots, coordinate lookup and six face neighbors;
a Metal kernel visits active bricks only. The report is `FluxFX Native Bricks.json`.
See [brick API, benchmark and limitations](docs/SPARSE_BRICKS.md). This remains
a storage/dispatch diagnostic; the visible smoke solver is still dense.

**P1.1 adds a persistent Metal context and a budgeted GPU arena**, packaged as
0.30.0. Set **Native arena (MiB)** and run **Test Resource Layer** in the native
panel. Repeated tests reuse the same backing buffer; **Release** frees it.
The report appears in `FluxFX Native Resources.json`. This is infrastructure for
sparse bricks, with no change to smoke physics yet. See
[resource API, limits and validation](docs/NATIVE_RESOURCES.md).

**P1.0 adds a compiled `fluxfx_core` Metal probe**, packaged as version 0.29.0.
Open **Native core · P1.8 → Test Native Metal Core**. The result is saved as
`FluxFX Native Core.json` in Blender's Text Editor. This proves native allocation,
compute dispatch, exact output verification, GPU command timing and cleanup.
The existing smoke engine remains the 0.28 dense reference. See
[native build/setup and evidence](docs/NATIVE_CORE.md) and the [P1 roadmap](docs/P1_ROADMAP.md).

Version 0.28 added a **bounded decoded-frame memory cache and nearby-frame prefetch**.
Set **Frame memory (MiB)** in the bake/playback panel (default 256; zero disables
retention). Revisited or prefetched frames avoid disk reads and decompression.
See [playback speed, memory accounting and limits](docs/FRAME_MEMORY.md).

Version 0.27 added optional **lossless cache compression**, exact float32 playback,
raw-frame fallback and bounded decompression. Enable **Lossless compression** in
the bake panel when storage matters; decompression adds playback cost. See
[compression setup and measured tradeoffs](docs/CACHE_COMPRESSION.md).

Version 0.26 added **animated-input baking**: keyframed emitter motion, size,
emission and heat, plus moving sphere/box colliders and animation-aware cache
invalidation. Enable **Animated inputs** in the bake panel. See
[setup, sampling rules and limits](docs/ANIMATED_BAKING.md).

Version 0.25 added **frame-range baking and timeline cache playback** with progress,
cancellation, storage estimates, and stale/corrupt cache checks. The first bake
workflow holds the current scene inputs fixed; animated inputs are not sampled.
See [bake/cache setup, storage and measured load costs](docs/CACHING.md).

Version 0.24 added **evolving turbulence at multiple scales**, with live strength,
size, speed, seed, density/heat masks and a bounded acceleration. Start with
**Turbulence → Strength 1–2**, Largest size **0.5 m**, and **Smoke** masking.
See [turbulence setup, comparisons and measured performance](docs/TURBULENCE.md).

Version 0.23 added **static mesh SDF collisions** for closed, consistently wound,
connected meshes. Select a mesh, choose **Colliders → Use Selected Mesh**, disable
Moving colliders, then Reset and Play. Display **Collision mask** to inspect the
resolved obstacle. Mesh transforms, geometry and modifier edits require Reset.
See [mesh setup, timings and limitations](docs/MESH_COLLISIONS.md).
Fuel/fire from [0.22](docs/COMBUSTION.md) and moving analytical colliders from
[0.21](docs/MOVING_COLLIDERS.md) remain available.

This milestone transports density through an evolving staggered MAC velocity field.
It includes approximate pressure projection inside a stationary closed box. Moving/deforming mesh collisions and wavelet upres are not implemented. Native coupled transport and projection remain diagnostic runs, not the interactive smoke engine. The default preview places the full 3D field inside a movable scene domain,
following perspective and orthographic viewport cameras. It is a transparent
viewport overlay without scene-object occlusion, lighting, or EEVEE/Cycles output.
The earlier 3D inset and diagnostic XZ slice remain available.

## Install in Blender 5.3

1. Use the macOS Apple Silicon Blender 5.3 build. On this machine it is
   `/Applications/Blender 2.app`. The other Blender app is a different version.
2. In **Edit → Preferences → Add-ons**, use the menu's **Install from Disk** action
   and choose **fluxfx-0.41.0.zip** (the extension ZIP, not the source ZIP).
3. Enable FluxFX if it is not enabled automatically.
4. Open a **3D Viewport**, press **N**, and select **FluxFX**.
5. Click **Run GPU Diagnostics**. A successful result is `READY`; the complete
   report is stored in the Blender Text Editor as `FluxFX Diagnostics.json`.
6. Click **Create Smoke Domain**, then **Reset** and **Play**. Select the domain
   box and press numpad decimal to frame it. Use G/R/S to move, rotate, or scale
   the smoke without resetting it. Initial velocity defaults to zero; heat drives
   the rise. Choose **View → XZ slice** for a cross section or **3D inset** for
   the previous preview. **Pause**, **Step**, and **Reset** work independently of the
   Blender timeline. **Release GPU Preview** frees the session's resources.

For obstacles, expand **Colliders**, add a Sphere or Box, and position it with
G/R/S. Enable **Moving colliders** before **Reset → Play** to move or rotate it live.
Size, shape, membership and mode changes require Reset. With moving mode disabled,
all collider edits require Reset and Auto pressure uses the masked multigrid hierarchy.
Choose Fast density and motion in Flow for lower cost, or Detailed for better retention
away from walls. Start moving-collider experiments at 32³.

Start at **64³**. The following storage figures apply without colliders. After the first step, default Detailed scalar/motion transport
and Auto pressure occupy about **24.873 MiB** at 64³ and **198.047 MiB** at 128³,
including reduction/multigrid scratch. Curl adds 4/32 MiB; a multi-source table
adds 512 bytes. Driver/shader/viewport overhead is excluded. On M5 Pro this comes
from shared system memory. Cycles' render-device preference does not select this
compute backend; inspect the backend reported by FluxFX's diagnostics.

The model is a **1 m cubic domain**. Initial upward flow is metres/second; initial rotation is
radians/second; source and decay rates are per second. The default maximum timestep is
1/30 s. Adaptive mode chooses a smaller step when the estimated CFL exceeds 0.75.
Playback uses a default **24 ms** work budget per callback and retains up to
**250 ms** of catch-up time. One expensive GPU step can exceed the budget; Blender
gets control again between callbacks. The speed display is simulated seconds per
wall second since Play. Lag and skipped time make overload visible. Pause/resume
starts a fresh clock; Step still advances one adaptive step. Live simulation has no timeline seek or guaranteed realtime rate. Use the separate
bake/cache workflow for timeline playback. A scripting-only checkpoint foundation
for fixed-input runs without colliders is documented in [combustion notes](docs/COMBUSTION.md). Completed-step timing includes a
tiny GPU readback; viewport rendering is outside the callback budget.

Click **Create Smoke Emitter** in Source to control emission with a spherical
Empty. Use **G** to move it and uniform **S** to change its radius. It is parented
to the domain; smoke and heat rates remain in the sidebar. Choose **Manual** to
return to numeric position/radius controls. Use **Add Another Emitter** for up to
seven more independently controlled spherical sources. Expand each entry for its
controls; disable or remove entries without clearing existing smoke. See
[multiple-emitter behaviour](docs/MULTIPLE_EMITTERS.md). Mesh voxelization is pending. Set **Jet velocity** and rotate with **R** for directional emission.
**Inherit motion** adds capped translation velocity; **Continuous trails** fills
the path between sampled positions. See [motion controls and limits](docs/EMITTER_MOTION.md).

**Source** and **Flow** controls apply on the next step, including during playback,
without resetting smoke. Move the source in metres within the 1 m domain, adjust
its radius, or turn **Emit smoke and heat** off to let existing smoke evolve.
Density/heat emission rates, decay, cooling, buoyancy, and pressure budget are live.
Grid, pressure-solver choice, and initial-state edits rebuild on the next Step/Play while paused. Reset
always reconstructs the initial seed, even if continuous emission is off.
Timestep changes preserve fields. Auto multigrid rescales and reuses the pressure
guess; the Jacobi fallback retains its legacy restart policy. Display mode, opacity, sample count, and slice
changes do not rebuild. Choose **Display → Temperature** to inspect heat: orange is above ambient, blue below.
The domain object and settings can be saved in `.blend` files, but GPU simulation
state is ephemeral and is not saved. Domain transforms affect visual placement;
physics still runs in a local 1 m box, with buoyancy along local +Z.
Loading a file, undo/redo, and disabling the add-on release it.

## Run from source without installing

In Blender's Scripting workspace, open `scripts/dev_load.py` from this repository
in the Text Editor, then choose **Run Script**. It registers FluxFX for the current
session. Re-running the loader stops/reloads the development modules safely.
Do not use the development loader alongside an installed copy of FluxFX.

This `FluxFX_Source/` folder is the only maintained source tree. The version
lives in `fluxfx/blender_manifest.toml`; `bl_info` mirrors it and a unit test
keeps the two equal.

The native diagnostic core is a build artifact, not source. Without Xcode, copy
the provenance-verified prebuilt into the package before using the dev loader:

```sh
python3 scripts/native_artifact.py install
```

After changing anything in `native/`, rebuild on Apple Silicon and record the
new artifact so its provenance matches the sources again:

```sh
python3 scripts/build_native.py
python3 scripts/native_artifact.py record --evidence docs/validation/<folder>
```

To build both distributable archives, from this folder:

```sh
python3 scripts/package.py
```

Outputs go into `dist/`. The extension has `blender_manifest.toml` at its ZIP root;
the source archive contains this tree without Git history, scratch files or
binaries. Packaging uses a fresh local build when present, otherwise the verified
prebuilt, and refuses a prebuilt whose recorded sources no longer match.

## Layout

```text
fluxfx/
  physics/         immutable grid/flow settings, CPU oracle for small tests
  backend/         diagnostics, GPU device adapter, dense ping-pong runtime
  shaders/         R32F image-store probe, source seed, advection kernels
  blender/         properties, UI/operators, session lifecycle, slice preview
native/            C++/Objective-C++/Metal sources and CPU tests
prebuilt/          verified native binary + PROVENANCE.json (build artifact)
scripts/           development loader, graphical GPU validation, packaging, CI checks
tests/             standalone numerical and diagnostics tests
docs/              architecture, API findings, validation evidence
```

The production playback path never runs voxel loops in Python and never reads
density back to the CPU. Adaptive stepping reads only five reduced scalar bounds
per step; this is synchronous and can stall. Explicit diagnostics and tests may
read complete fields.
The [architecture note](docs/ARCHITECTURE.md) maps this implementation to Phase 3.

## Validation

Everything that runs without graphical Blender, from this folder (CI runs the
same command on every push):

```sh
python3 scripts/ci_checks.py
```

It byte-compiles all Python, runs the standalone unit suite, checks the prebuilt
native provenance and builds/runs the native CPU tests (`arena`, `bricks`,
`regions`). Use `--skip-native` without a C++ compiler. The unit suite alone:

```sh
python3 -m unittest discover -s tests -v
```

GPU validation must run in a graphical Blender process. This command opens a
fresh factory session, tests it, writes JSON, and quits **that process**:

```sh
"/Applications/Blender 2.app/Contents/MacOS/Blender" \
  --factory-startup --python scripts/gpu_validate.py \
  -- --output test-results/gpu-validation.json
```

Check the JSON `status` is `PASS`; Blender process exit status alone does not
indicate test success. **Do not add `--background`**. In sandboxed automation,
launching a GUI process may be unavailable. In an existing Blender Python Console
you can instead run the suite without quitting Blender:

```python
import runpy
suite = runpy.run_path("/absolute/path/to/fluxfx/scripts/gpu_validate.py", run_name="fluxfx_validation")
report = suite["run_suite"]()
print(report)
```

The suite registers/unregisters FluxFX; run it with any existing FluxFX session
disabled. Save unrelated work before development testing in an alpha build.
For P0.3 MAC GPU validation, run this in Blender's Python Console:

```python
import runpy
suite = runpy.run_path("/absolute/path/to/fluxfx/scripts/mac_validate.py", run_name="mac_validation")
report = suite["run_suite"]()
print(report)
```

It checks signed face fields, non-cubic physical spacing, simultaneous component
updates, density coupling, reset, and 64³/128³ runs. Like the baseline suite, it
requires an interactive GPU context.

For P0.4 validation, use the same `runpy` pattern with
`scripts/thermal_validate.py`. It checks coupled temperature transport, heating
and cooling, force directions/equilibrium, exact zero-force equivalence to P0.3,
and 64³/128³ runs. It performs synchronous readback only for validation.

For P0.5 GPU validation, use the same pattern with `scripts/pressure_validate.py`.
It checks pressure/velocity against a CPU oracle, manufactured gradients, closed
walls, scalar constants, and divergence reduction at 64³ and 128³.

For P0.6 live-source GPU checks, use `scripts/interactive_validate.py` with the
same `runpy` pattern. It verifies source movement, emission-off preservation,
pressure-budget edits, and rejected initial-state edits.

For P0.7 render validation, run `scripts/volume_validate.py` in graphical
Blender after loading the source add-on. It compares float framebuffer pixels
against analytic optical-depth results at 64/128/256 ray samples.

For P0.8 GPU validation, run `scripts/timestep_validate.py` after loading the
source add-on. It checks reduction values, invalid fields, and adaptive 64³/128³ runs.

For P0.9 benchmarks, load the source add-on and run `scripts/benchmark.py`
through `runpy` with `run_name="__main__"` in a graphical Blender console. It
pauses current playback, uses separate test fields, and writes
`test-results/benchmark.json`. The UI is busy during the run. Read the
[methodology](docs/P0_9.md) before interpreting timings.

For version 0.10 solver checks, run `scripts/multigrid_operators_validate.py`
and `scripts/multigrid_validate.py` after loading the source add-on. They check
transfer kernels, residuals, resets, matched-input accuracy/timing, and coupled
64³/128³ simulations.

For 0.11 scene rendering tests, run `scripts/scene_validate.py` after loading
the source add-on. It checks camera rays, transformed domains, compositing,
zero scale, and preservation of simulation state.

For 0.12 emitter validation, run `scripts/emitter_validate.py` after loading
the source add-on. It checks transforms, animation, GPU injection, and failure
handling. It restores settings but releases the active GPU session.

For timer/resource lifecycle testing, run `scripts/ui_validate.py` in the Text
Editor. It writes `test-results/ui-validation.json` and leaves a paused preview
for visual inspection; it does not quit Blender.

For 0.17, see [motion detail validation](docs/MOTION_DETAIL.md).
For 0.16, run `scripts/detail_validate.py` in graphical Blender. See
[smoke detail and benchmark reproduction](docs/SMOKE_DETAIL.md) for new controls,
quality comparisons, memory costs and limitations.

## Numerical behavior and next step

P0.3 stores U `(Nx+1, Ny, Nz)`, V `(Nx, Ny+1, Nz)`, and W `(Nx, Ny, Nz+1)`
velocity components on cell faces. Each component self-advects through the same
old velocity field before all three swap together. Density then follows the new
velocity. P0.4 inserts buoyancy after velocity transport and before scalar transport.
The original P0.2 and P0.3 backends remain available for regression tests.

Midpoint semi-Lagrangian backtracing and trilinear interpolation transport velocity;
0.17 optionally adds limited MacCormack correction (Motion transport → Detailed).
Density and temperature optionally use bounded MacCormack correction (Detailed).
Density supports additive or target emission with soft or solid spherical profiles.
The historical P0.2–P0.4 backends use open-domain prototype boundaries.
P0.5 uses zero normal velocity at closed free-slip walls and clamped scalar sampling. Transport is
diffusive and not mass conserving. Initial rotation/upward speed seed the flow
on Reset; they do not overwrite the evolving field each frame.

P0.4 adds signed temperature excess above ambient, a heat source, exponential
cooling, and vertical acceleration `heat_lift * temperature - density_weight * density`.
The coefficients include gravity scaling; this is a prototype buoyancy model.
Face acceleration uses the adjacent cells' mean density and temperature.
Temperature and density then advect through the forced velocity. Newly injected
heat affects velocity on the following step. The historical P0.4 backend uses zero extension for both scalars.

P0.5 projects the forced velocity before transporting scalars. Weighted Jacobi uses
80 base iterations at 64³, scales with resolution squared, and uses four times
that budget on a cold solve. Subsequent solves reuse pressure at the same timestep.
These budgets describe the retained Jacobi baseline. The 0.17 multigrid default uses two
V-cycles and a direct 4³ coarse solve. Both budgets are approximate; convergence
depends on the flow. Click **Measure
Divergence** after a step to pause and inspect before/after RMS plus the actual
iteration count. The full report is stored as `FluxFX Projection.json`.

**P0.9 completes the initial dense prototype with measured benchmarks.**
Version 0.10 adds a faster multigrid pressure solver. **Auto** keeps Jacobi below
128³ and selects multigrid at 128³ in that historical milestone. Version 0.17
selects multigrid for coarsenable grids from 16³ and defaults to two cycles. The setup panel allows manual comparison;
the Flow panel exposes Jacobi iterations or multigrid V-cycles (default two in 0.17).
The new solver improves both speed and sampled divergence reduction at 128³.
See the [comparison and limits](docs/MULTIGRID.md).
Version 0.11 adds a scene-space domain. The viewport overlay has no scene-depth
occlusion, lighting, shadows, or render-engine output. Adaptive estimates include current transport, buoyancy and curl-force bounds, but
not possible velocity increases from pressure projection; no realtime
performance guarantee is claimed.

See [API limitations](docs/API_LIMITATIONS.md) before extending the backend.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
