# Version 0.14 — multiple spherical emitters

FluxFX supports **eight sources total**: the existing primary source (Manual or
Object mode) and up to seven additional Empty-controlled sources. Each additional
source has its own enable switch, density/heat rates, jet velocity, coupling,
motion inheritance, speed limit, and continuous-trail setting. Domain, grid,
buoyancy, cooling, pressure, and playback remain shared.

## Workflow

1. Use **Create Smoke Emitter** for the primary source, then Reset and Play.
2. Open **Additional emitters** and click **Add Another Emitter**. A new spherical
   Empty is created at the primary manual source position/radius and parented to
   the domain. It starts with default emission settings and is selected.
3. Move with **G**, rotate the jet with **R**, and resize with uniform **S**. Expand
   the arrow beside an entry to edit its settings. The object picker can assign
   an existing Empty instead.
4. Uncheck an entry to stop only that source. Its existing smoke continues to
   evolve. The primary source checkbox controls only the primary source.
5. The **X** removes an additional source entry, retaining the scene object and
   already-emitted smoke. Assign that object to another entry to use it again.
   Undo/redo follows the existing policy of releasing GPU state.

Addition, removal, per-source settings, and object transforms apply on the next
step without resetting the field. Eight is an intentional P0 limit, including
inactive entries and the reserved primary source slot. Assigning the same object
to multiple entries intentionally adds multiple contributions.

A missing enabled additional source pauses with an explicit error before another
simulation step. Disabled entries may have no object. Enabling them requires a
valid object. Hiding an Empty's helper is not an emission switch.

## GPU implementation

The original single-source path remains active when no additional sources are
enabled. Multiple sources use a **512-byte R32F 4×4×8 source table**, one 16-float
plane per source: center/radius, previous position/coupling, target velocity/density
rate, and heat rate. Signed values are supported. Changed source data uploads a
replacement small texture; unchanged data reuses the table. There are no full
simulation-field transfers to the CPU.

The GPU sums density and heat contributions using the existing swept-sphere
profile. For overlapping jets, it sums local coupling rates and takes their
weighted target velocity before applying exponential relaxation. This avoids
list-order priority. Pressure projection runs once after combined source forcing
and buoyancy. The adaptive timestep considers every active jet's target speed.
Multi-source kernels use the existing pass count and field storage plus the table;
kernel arithmetic increases with active source count. This release has no new
end-to-end FPS benchmark or real-time guarantee.

Per-source history uses a saved unique entry ID, so removing one entry does not
reassign another's trail. Disabled sources drop their history; re-enabling starts
at the current position. Pause/resume, reset, domain changes, and timeline jumps
retain the 0.13 discontinuity policy. The source collection, settings, and object
links are saved in `.blend` files. GPU state and motion history remain ephemeral.

Reset preserves the legacy initial density/heat seed at the primary source.
Additional sources start injecting on the first simulation step; they do not add
extra initial seeds. This is independent of their ongoing per-second rates.

## Validation

Tested on Blender 5.3.0 Alpha b2e052b7172a, Apple M5 Pro / Metal:

- 66 standalone tests pass, including source packing, capacity, and invalid data.
- 22 multi-source GPU/Blender checks pass: analytic overlapping density and signed
  heat sums, table reuse, order independence, empty/eight-source batches, capacity,
  interacting jets, pressure correction, single-source equivalence, adaptive
  timestep, live editing, history, disabled/missing sources, removal, and cleanup.
- The existing 18 motion, 11 object-emitter, and 17 UI/lifecycle checks pass.
- A separate Blender process saves and reopens a temporary `.blend`, confirming
  collection count, stable IDs, settings, object links, and parenting.

Overlapping-source maximum errors were 2.36e-8 density and 2.21e-7 heat; the isolated
16³ multi-jet projection retained 1.53% of provisional divergence RMS.

Run `scripts/multiple_validate.py` in graphical Blender after the development
loader. Run `scripts/source_save_validate.py` using background factory-startup
Blender; it creates and deletes its own temporary file.

[Multi-source results](validation/m5-pro-multiple-014.json) ·
[Save/reopen results](validation/m5-pro-source-save-014.json) ·
[Motion](validation/m5-pro-motion-014.json) ·
[Emitter](validation/m5-pro-emitter-014.json) ·
[UI](validation/m5-pro-ui-014.json).

All sources remain spherical. Mesh voxelization, collisions, sparse grids,
timeline baking, scene depth occlusion, and EEVEE/Cycles output remain pending.
