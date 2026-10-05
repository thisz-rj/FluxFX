# Version 0.13 — emitter motion and velocity

Historical milestone notes. Version 0.14 adds [multiple emitters](MULTIPLE_EMITTERS.md).

A spherical source can inject directional velocity, inherit translation, and leave
continuous trails. Tested in Blender 5.3.0 Alpha b2e052b7172a on Apple M5 Pro / Metal.

## Use it

1. Create a Smoke Emitter, then Reset and Play at 64³.
2. Set **Jet velocity (m/s)**, for example `(0, 0, 1)`. In Object mode it uses
   emitter-local axes: **R** rotates the jet, **G** moves it, and uniform **S**
   changes the source radius. Manual mode uses domain axes.
3. Increase **Inherit motion** from its default 0 toward 1 to transfer movement
   into the smoke. **Inherited speed limit** defaults to 2 m/s and bounds only
   that motion contribution; the directional jet is added afterward.
4. **Continuous trails**, enabled by default, emits along the straight path
   between sampled positions. Turn it off for endpoint-only emission.
5. **Velocity coupling /s** controls how quickly flow approaches the target jet
   velocity inside the source. Zero disables velocity injection. Turning emission
   off disables smoke, heat, and velocity injection together.

All controls apply on the next simulation step without clearing existing smoke.
With jet zero and inheritance zero, velocity coupling is bypassed, preserving
previous buoyancy-driven behaviour. When inheritance is enabled, a stationary
emitter couples toward zero velocity (or toward the configured jet).

## Numerical model

`physics/emission.py` holds the per-step source description and capped translation
velocity. `blender/emitter.py` handles evaluated transforms/history; Blender UI
code contains no fluid calculations. The GPU applies source forcing to advected
MAC face velocities, then buoyancy and pressure projection, before transporting
and injecting density and temperature. Coupling uses
`1 - exp(-coupling * dt * weight)` toward the target velocity. Projection changes
the final velocity to satisfy the closed-box constraint; the target is not an
exact prescribed post-projection nozzle speed.

The trail weight is the analytic time-average of the existing compact spherical
profile `(max(1-distance²/radius²,0))²` along a segment. This avoids gaps from
sampling a few discrete spheres, and distributes the step's source budget over
the path instead of multiplying emission by path length. A longer trail is thus
fainter. Density and heat use the same weight. Radius and jet orientation use the
current sample throughout the segment; curved paths between samples are not
reconstructed. Sources smaller than grid cells can still be under-resolved.

No new field allocations, compute dispatches, or full-field readbacks are needed
in normal playback. The existing velocity-advection and scalar kernels incorporate
the source work. Adaptive stepping includes the source target speed in its bound;
this remains a conservative estimate, not a hard post-projection CFL guarantee.
No new end-to-end FPS claim is made.

## Time and history

For consecutive advancing Blender frames, inherited speed uses frame difference
and scene FPS. While dragging at the same frame, it uses the configured maximum
simulation step as the sampling interval. This is a predictable preview control,
not mouse speed measured against wall time. Adaptive reduction does not inflate
inherited velocity. The full sampled path is emitted within the chosen simulation
step; there is no timeline catch-up or baking.

Reset, release, pause/resume, changing the emitter/source mode, toggling emission,
changing the domain transform, backward timeline movement, and forward jumps over
one frame start fresh source history. Ordinary repeated Step actions retain the
last completed step's history. Failed steps do not commit a new history sample.
Undo/load/disable retain the existing GPU-session cleanup behaviour.

The simulation stays in a local 1 m domain. Domain transforms affect placement,
not moving-wall physics. A quaternion extracted from the relative object transform
orients the jet; uniform emitter scale is recommended. Sheared/reflected transforms
are not a physically exact nozzle model. No angular velocity inheritance, mesh
sources, multiple emitters, collisions, timeline cache, scene occlusion, or final
render integration is included.

## Validation

- 62 standalone tests pass.
- 18 motion checks pass on Metal: GPU density/heat against independent numerical
  quadrature, continuous trail coverage, reverse-path symmetry, three jet axes,
  pressure correction, adaptive timestep response, rotated jet, capped inherited
  speed, emission off, timeline/domain discontinuities, live solver preservation,
  and pause cleanup.
- Existing 11 object-emitter checks and 17 UI/lifecycle checks pass. The older
  emitter injection test explicitly disables trails to retain its endpoint oracle.

Maximum trail errors were 2.72e-7 density and 4.08e-6 heat. In the isolated 16³ jet
checks, pressure correction left about 0.76% of the provisional divergence RMS.
These are numerical checks, not visual realism or performance guarantees.

Run `scripts/motion_validate.py` in graphical Blender after `scripts/dev_load.py`.
It uses a temporary scene and restores the previous one, releasing GPU state.
[Motion evidence](validation/m5-pro-motion-013.json) ·
[Emitter evidence](validation/m5-pro-emitter-013.json) ·
[UI evidence](validation/m5-pro-ui-013.json).
