# Phase 3 → Phase 4 implementation

P0.0–P0.2 baseline design below is retained for comparison. P0.3 adds evolving MAC velocity; see [P0.3](P0_3.md) for its pass contract.
P0.4 adds temperature and buoyancy; see [P0.4](P0_4.md).
P0.5 adds closed-box pressure projection; see [P0.5](P0_5.md).
P0.6 adds live source/flow settings without field reallocation; see [P0.6](P0_6.md).
P0.7 adds GPU volume raymarching; see [P0.7](P0_7.md).
P0.8 adds GPU-reduced adaptive timestep estimates; see [P0.8](P0_8.md).
P0.9 adds synchronized benchmark evidence; see [P0.9](P0_9.md).
Version 0.10 optimizes dense pressure with geometric multigrid; see [multigrid](MULTIGRID.md).
Version 0.11 adds a scene-owned domain Empty and camera-correct viewport overlay; see [scene domain](SCENE_DOMAIN.md).
Version 0.12 maps an evaluated emitter Empty into the existing spherical source; see [object emitters](OBJECT_EMITTERS.md).

Design reference: the user's **Blender PyroFX Addon Plan**, Phase 3F and its
explicit P0.0–P0.9 sequence. Phase 3's complete P0 solver specification is the
destination; it is not all included in P0.2.

| Milestone | Implemented here | Validation |
| --- | --- | --- |
| P0.0 | Defensive version/device/backend/capability report | Missing API and background-context tests; actual M5 Pro report |
| P0.1 | Writable R32F 3D texture, bounds-checked compute dispatch | Exact 105-texel XYZ pattern on a 7×5×3 grid |
| P0.2 | Dense density ping-pong, prescribed flow, source, decay | GPU/CPU agreement, analytic invariants, 64³/128³ runs |
| UI scaffold | Registration, scene settings, operators, runtime ownership | Repeated registration, pause, reset, release, visible slice |

## Dependency direction

`blender → backend → physics`.

`physics` contains immutable values and a small independent CPU reference used
only by validation. It does not import `bpy` or `gpu`. `backend/device.py` owns
the Blender GPU adaptation and dispatch policy. `backend/dense.py` composes
simulation passes and owns textures. `backend/diagnostics.py` also reads Blender
build/context metadata, but does not access scenes or UI. `blender` converts
scene settings into descriptors and owns timers/draw handlers. GLSL contains all
production per-voxel arithmetic.

## P0.2 field and pass contract

- Cell-centered density A/B: `Nx × Ny × Nz`, R32F, x-fast CPU readback layout.
- Domain coordinates: metres, origin `(0, 0, 0)`, extent `(1, 1, 1)` in the UI.
  Cell centers are `(i + 0.5) * extent / shape`; backend supports non-cubic grids.
- Source: smooth compact sphere centered at `(0.5, 0.5, 0.16)` with radius 0.12 m.
  Weight is `max(1 - squared_distance / radius², 0)²`.
- Reset: clear both textures, write one unit-strength source into the front field.
- Step: trace through the analytic velocity using the midpoint rule, gather the
  old density, apply `exp(-decay * dt)`, add `source_rate * dt * source_weight`,
  write every destination voxel, then swap references. Injection after transport
  is P0.2's chosen splitting; later complete fluid passes can change that order.
- Velocity: constant vector plus XY rigid rotation about the domain center.
  There is no collocated velocity texture that will need migration to MAC later.
- Boundaries: fetch zero outside the cell array; no wrapping/clamping, no walls.
- Dispatch: 4×4×4 local groups, rounded up; every kernel bounds-checks IDs.
- Step/read dependencies use Blender's dispatch barriers. No source/destination
  aliasing and no readback between normal playback steps.

## Ownership and lifecycle

One preview session exists at a time, associated with one Blender scene. The
session owns its two textures, compute shaders, display shader/batch, draw
handler, and application timer. Everything executes on Blender's main thread.
No Python worker threads, no asynchronous writes into Blender data.

Pause removes the timer but retains the preview. Release/disable/load/undo/redo
remove the timer and handler and drop owned GPU references. Reset builds a fresh
session. Switching scenes pauses playback. Returning to the owning scene can
show its paused field; initializing another scene replaces the old session.
GPU exceptions stop playback and surface an error instead of continuing to
dispatch. The simulation is neither an undoable state history nor a bake/cache.

## Deferred in the prescribed order

P0.3: staggered MAC velocity. P0.4: buoyancy. P0.5: divergence, weighted Jacobi,
pressure-gradient subtraction and measured divergence reduction. P0.6: actual
interactive smoke. P0.7: viewport volume raymarching. P0.8: CFL/substeps.
P0.9: broader validation/benchmarks. P1: native device abstraction and sparse
brick infrastructure. No APIC, allocator, C++ stubs, or multigrid scaffolding is
introduced before those foundations are measurable.

- 0.13: per-step `physics.emission.Emission` separates motion from persistent settings. Blender supplies evaluated history; GPU kernels integrate swept source weights and velocity coupling before projection. See [emitter motion](EMITTER_MOTION.md).

- 0.14: `Source` batches keep per-source data separate from shared solver settings. A cached 512-byte source table feeds additive scalar and order-independent jet kernels; the primary-only path remains available. See [multiple emitters](MULTIPLE_EMITTERS.md).

- 0.15: measurement-only native comparison, with exact simulated-time output boundaries, synchronized GPU timings, native Replay evaluation, and common diagnostic rendering. No physics change; see [results and limits](NATIVE_COMPARISON.md).
