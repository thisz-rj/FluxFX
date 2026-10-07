# 0.21 — Moving sphere and box colliders

Enable **Moving colliders** in the Colliders panel, then Reset and Play. Translate
or rotate a collider Empty while smoke runs. Pause and Step also support motion.
Start at 32³; use Fast density/motion for lower cost. Changing size, shape, object
assignment, enabled entries, or moving mode requires Reset. Positive, fixed scale
is supported, including ellipsoids and nonuniform boxes; shear is rejected.

Motion is expressed in the solver's 1 m domain. Translation and shortest-arc
quaternion rotation are interpolated. Surface speed is capped at 2 m/s using a
conservative radius bound; each substep moves the boundary at most half a cell.
Fast drags therefore trail the object. The panel reports the remaining tracking
gap. It is a conservative surface-distance bound, including rotation, not just
centre distance. Paths use the latest sampled object transform, not a recorded
trajectory between UI callbacks. Timeline seeking does not reconstruct smoke.

## Method and limits

The physics path is independent of Blender UI. Each motion substep rasterizes
one to eight analytical primitives into a GPU owner mask, computes MAC face wall
velocities from rigid translation/angular velocity, then remaps the fields.
Covered and newly exposed scalar cells are emptied; newly opened velocity faces
start at zero. Wall-normal velocity is imposed before and after projection.
Stationary domain walls remain zero. Detailed transport retains its wall fallback.
Overlaps use the first enabled collider's ownership; this is not contact physics.

Moving mode uses masked GPU Jacobi pressure even when Auto/Multigrid is selected.
The static multigrid hierarchy is not rebuilt during drags. Pressure starts from
zero; moving geometry invalidates the previous projection measurement. Direct
backend callers must call `move_colliders` with a `MotionPath`-bounded interval
before every `step`, including a stationary update when the object stops.

This is a voxel prototype: no cut cells, exact mass conservation, mesh obstacles,
two-way rigid-body coupling, or friction. Emptying covered/exposed cells loses
smoke/heat. Rotation changes voxel volume, so the prescribed wall flux can have
residual incompatibility with a closed incompressible domain; short Jacobi solves
leave residual divergence. Thin obstacles below grid resolution are unreliable.
The cap limits sampled motion, not fluid speed, and does not guarantee stability
for arbitrary user forces or tightly packed colliders.

## Measured on Apple M5 Pro / Metal

Blender 5.3.0 Alpha `b2e052b7172a`, 2026-09-27. The 64³ benchmark runs two simulated
seconds per case, with a translating and rotating fixed-size primitive, default
thermal/source settings, 80 Jacobi iterations, adaptive timesteps, GPU mask refresh,
and a completed-GPU fence. Compilation is warmed up; viewport drawing is excluded.
These are mild motion scenes, not the stronger 0.20 jet stress scenes.

| Collider | Transport | Sim seconds / wall second | Median 1/30 s frame | p95 |
|---|---|---:|---:|---:|
| Sphere | Fast | 2.77 | 12.59 ms | 14.83 ms |
| Sphere | Detailed | 1.85 | 18.69 ms | 20.11 ms |
| Box | Fast | 2.17 | 13.35 ms | 19.90 ms |
| Box | Detailed | 1.44 | 19.56 ms | 29.31 ms |

All four runs had finite bounded fields and zero smoke/heat in solids. These
solver timings exceed realtime in these scenes; interactive viewport rate is not
guaranteed. More colliders, faster motion, strong emitters and larger grids cost more.

The 32³ GPU suite checks masks against a CPU reference, actual newly exposed cells,
normal wall velocities, fluid displacement, divergence reduction, stationary wall
stopping, fast rotation and resize rejection. The live Blender suite checks moving
objects during timer playback, pause/Step, live transport changes, resize Reset
handling and undo cleanup. Raw reports are in [validation/moving021](validation/moving021).

Run `scripts/moving_collider_validate.py`, `scripts/moving_collider_ui_validate.py`
and `scripts/moving_collider_benchmark.py` in graphical Blender after `dev_load.py`.
The UI suite completes asynchronously. Save/load validation can run in background.
