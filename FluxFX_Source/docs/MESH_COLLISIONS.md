# 0.23 — Static mesh SDF collisions

## Setup

1. Install `fluxfx-0.23.0.zip` and create a FluxFX domain.
2. Place a **closed mesh** inside the domain and select it in Object Mode.
3. Choose **Colliders → Use Selected Mesh**. This links the existing object;
   it does not reparent it, replace its mesh, or add a native fluid modifier.
4. Disable **Moving colliders**, choose 32³ or 64³, then **Reset → Play**.
5. Select **Display → Collision mask** to inspect the actual voxel obstacle.
   Use XZ slice for a cross section, or Scene volume/3D inset for the full mask.
   Return to Density or Flame to inspect the simulation.

One collider entry accepts one connected, closed mesh shell with consistent winding
and at most 50,000 evaluated triangles. Up to eight enabled mesh/primitive entries
can be combined. Meshes are evaluated with modifiers and transformed into simulation
coordinates; unapplied scale and rotation are supported. Entering Edit Mode,
changing geometry/modifiers, or moving the mesh requires leaving Edit Mode and
Resetting. Adding/removing/enabling entries also requires Reset.

Open edges, edges with more than two faces, inconsistent winding, degenerate
triangles, disconnected shells, detected nonadjacent self-intersections and zero
volume generate errors. Globally reversed winding is supported. This validation
is not a general mesh repair or a proof against every pathological self-contact.
Use clean, non-self-intersecting closed geometry. Multiple disconnected objects
should use separate collider entries, not a single joined mesh.

Mesh colliders cannot be combined with the Moving colliders mode in this release,
even if only the analytical objects would move. Static spheres and boxes can be
combined freely with static meshes. Smoke, temperature, fuel and flame are excluded
from all occupied cells.

## What the SDF does

On Reset, the CPU constructs a BVH from evaluated triangles. Nearest-surface queries
provide unsigned distance. Three non-axis-aligned ray directions vote on whether
their first hit exits or enters the consistently wound shell; signed volume accounts
for reversed winding. This gives a sampled signed distance in simulation metres:
negative inside, positive outside. Surface samples use a small numerical tolerance.
The implementation uses Blender's public [BVHTree API](https://docs.blender.org/api/current/mathutils.bvhtree.html).

The mesh SDF is uploaded as R32F, and its zero threshold is unioned with the existing
analytical masks. The pressure/advection solvers currently use **voxel boundaries**;
this is not a cut-cell or subvoxel pressure solver. SDF gradients are not yet used
for contact normals or wall interpolation. For overlapping meshes, minimum SDF
values give the union sign but are not an exact interior union distance. The stored
SDF covers mesh entries; the collision preview includes meshes and primitives.

Auto pressure uses the existing obstacle-aware multigrid hierarchy, with its
connectivity safeguards and fallback. Detailed transport retains its near-wall
fallback. There is no mesh-to-smoke feedback, friction, mesh motion, deformation or
native rigid-body coupling.

Features should be at least two grid cells thick. Thin bounds trigger a warning;
that simple check cannot detect every thin appendage. Features smaller than a cell
may vanish or leak, and narrow holes may close. A mesh occupying no cell is rejected
with a resolution/placement message. Inspect Collision mask at the intended grid.

Preparation blocks Blender during Reset. Evaluated geometry is compared during
playback to detect edits, so complex meshes/modifiers also add CPU overhead during
Play. There is no persistent SDF cache yet. Checkpoint v1 from 0.22 still excludes
all colliders; `.blend` save/load preserves mesh assignments and settings, not GPU
simulation state.

## Measured on M5 Pro / Metal

Blender 5.3.0 Alpha `b2e052b7172a`, 2026-09-28. A 768-triangle torus, a mild thermal
smoke source, Detailed transport, Auto pressure, three simulated seconds. Stepping
includes adaptive reductions and completed-GPU fences. Compilation is warmed up;
viewport drawing and scene geometry polling are excluded from stepping timings.
The separate snapshot number estimates polling cost for this small mesh.

| Grid | SDF build | Total solver setup | Sim seconds / wall second | Median 1/30 s frame | p95 |
|---|---:|---:|---:|---:|---:|
| 32³ | 0.051 s | 0.099 s | 8.71 | 3.14 ms | 6.09 ms |
| 64³ | 0.367 s | 0.699 s | 1.98 | 16.40 ms | 24.60 ms |

Geometry snapshots averaged about 0.48 ms. The retained SDF plus union mask uses
0.25 MiB at 32³ and 2 MiB at 64³, regardless of mesh count. Total measured GPU field
storage was about 3.97/31.44 MiB respectively, excluding driver overhead and CPU BVH,
evaluated meshes and temporary arrays. Larger meshes, complex modifiers, narrow
channels and strong fire sources can cost substantially more. These rates do not
establish viewport realtime performance or replace the slower 0.22 fire benchmark.

## Verification

- Box mask matches the analytical box; signed-distance maximum error below 5e-8 m.
- Polygonal sphere/torus distances stay within 0.00265/0.00448 m of ideal surfaces
  at 32³. Those differences include polygon approximation, not just numerical error.
- Torus sign matches the analytical sign outside a 0.006 m surface band; its central
  hole remains fluid. Globally reversed normals preserve signs.
- Thin-feature warning, open/degenerate geometry errors, evaluated modifiers,
  transform/vertex changes, static-only mode, mesh/primitive union, smoke/fire
  exclusion, save/load links and preview pixels are checked.
- The rendered collision-preview test verifies an opaque ring and transparent
  central hole/outside region using the actual GPU mask.

Reports and the preview image are in [validation/mesh023](validation/mesh023).
Run `scripts/mesh_validate.py`, `scripts/mesh_ui_validate.py`,
`scripts/mesh_benchmark.py` and `scripts/mesh_preview_validate.py` in graphical
Blender after `scripts/dev_load.py`. The first three also support
`run_suite(gpu_test=False)` for CPU-only checks. `mesh_save_validate.py` runs in
background Blender. Standalone topology tests are in `tests/test_mesh.py`.
