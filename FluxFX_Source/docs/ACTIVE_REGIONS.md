# P1.3 — Active regions and brick preview (0.32.0)

P1.3 connects the native brick pool to source-driven activation, predicted-motion
coverage, a configurable halo, delayed deactivation and a Blender wire preview.
This is topology infrastructure. The displayed smoke solver remains dense;
there is no native sparse density transport yet.

## Use in Blender

Install `fluxfx-0.32.0.zip` and restart Blender after replacing a loaded native
module. Create a FluxFX domain and emitter with the existing controls. Open
**Native core · P1.3**, then choose **Show Active Bricks**. Move or resize the
emitter. Cyan bricks are required by the current source/halo calculation;
orange bricks are temporarily retained after becoming unnecessary. Multiple
emitters and Manual source mode are supported. **Hide Active Bricks** releases
the native pool and removes the overlay.

The preview uses 8³ bricks. Sparse domain grid defaults to 256 and accepts
64–512, rounded down to a multiple of eight. Brick capacity defaults to 4,096;
the UI allows 64–16,384 slots. Native arena (MiB) limits the backing buffer,
including its reserved field and GPU topology. It excludes CPU metadata,
Blender drawing batches, driver allocations and other native contexts.

- **Safety halo (bricks):** adds 0–4 brick widths on every side; default 1.
- **Inactive steps:** removes a brick on its Nth consecutive unnecessary update;
  default 3. A required brick resets its age to zero.
- **Flow speed bound:** additional conservative speed in domain lengths/second;
  expands every side by bound × timestep. Default zero.
- The existing **Max step (seconds)** supplies the prediction interval.

The preview requests updates every 0.1 seconds, advancing one topology step per
callback. These steps are not simulation substeps or elapsed-time catch-up.
Changing grid, capacity or arena budget stops the preview; click Show again to
recreate it. Other controls are read on each update. Undo/redo, file loading,
add-on shutdown and switching scenes stop it. The overlay follows the evaluated
domain transform and is depth-tested against scene geometry.

## Native contract

```python
from fluxfx.native import BrickPool
with BrickPool(8, 4096, 16*2**20) as pool:
    # center xyz, radius, predicted velocity xyz, in normalized domain units
    sources = [(0.5, 0.5, 0.2, 0.04, 0.0, 0.0, 1.0)]
    pool.update_regions(sources, grid=32, dt=1/30, linger=3, halo=1)
    rows = pool.snapshot()  # x, y, z, reusable slot ID, inactive age
```

`grid` is the number of bricks per domain axis, 1–64. Sources use normalized
[0,1] domain coordinates and velocity in domain lengths/second. Up to 64 source
tuples are accepted by the native API; the Blender UI supplies at most eight.
The native calculation covers the axis-aligned bounds of each sphere swept
from center to center + velocity × dt, adds the brick halo, and clips to the
domain. It is conservative box coverage, not exact sphere/brick intersection.

Blender supplies the existing emitter jet and inherited-motion estimate. The
optional flow-speed bound adds coverage for unknown directions. There is no
native fluid velocity field yet, so this is not a guarantee that an evolving
smoke field will remain covered. P1.4/P1.5 must add field-based support retention
and transport-aware prediction before discarding physically significant bricks.

A fixed 64³-byte scratch mask deduplicates required coordinates. A preallocated
age array tracks each pool slot. The planner scans the brick-domain mask, so its
CPU cost is O(grid³ + source coverage + active count), even for empty regions.
It does not scan a dense voxel field. The topology's active vector remains
compact after every update through swap-removal and appending newly activated
slots. Neighbor IDs are refreshed when the existing diagnostic dispatch runs.

The update first counts required and retained bricks. If they exceed capacity,
it rejects the entire update before changing slots or ages. The Blender preview
reports the failure and releases its pool; it never silently clips to capacity.
Direct API callers retain the prior topology after a failed update.

No density values are inspected or preserved by this planner. Deactivation here
means “not required by sources/prediction for N updates,” not “physically empty.”
The existing `probe()` is still a destructive integer diagnostic. Python handles
source commands and preview line construction; the region and voxel work stays
in native C++/Metal. Preview geometry is rebuilt on each update and is not yet
optimized for large brick counts.

## Validation

Apple M5 Pro, Blender 5.3 Alpha `b2e052b7172a`, Python 3.13.13:

- 24 native region/GPU integration checks passed, including directional velocity,
  clipping, duplicate sources, expiry, reactivation, capacity atomicity and exact
  Metal verification after topology changes.
- 13 Blender checks passed: emitter movement, multiple emitters, retained-color
  batches, disabled sources, stop, undo/load, setting changes and actual
  scene-switch timer cleanup. Owned GPU bytes returned to baseline.
- The cyan wire preview was visually inspected in the graphical viewport.
- 4,000 repeated C++ updates plus region contract assertions passed with address
  and undefined-behavior sanitizers.
- P1.2 regression: 54 checks passed. P1.1 resource regression: 29 checks passed.
- 146 standalone Python tests and 15 Blender save/load checks passed.

Evidence is in `validation/native_p13/`. Run `scripts/regions_validate.py` and
`scripts/regions_ui_validate.py` inside graphical Blender (register FluxFX first
for the UI test). The portable CPU test is `native/regions_test.cpp`.

Next: P1.4 sparse density advection, with matching dense-reference inputs,
numerical error, mass, memory and completed-step timing. No fluid speedup or
realtime smoke claim follows from this topology preview.
