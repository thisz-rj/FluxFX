# 0.26 — Animated-input baking

Enable **Animated inputs** in **Bake and cache playback** to sample direct
Blender keyframes while baking. The default remains the fixed-input workflow.

## Use

1. Install `fluxfx-0.26.0.zip` in Blender 5.3. Configure a domain and emitters.
2. Keyframe emitter location and uniform scale, and source emission/heat controls.
   Additional emitters are supported. Existing live-adjustable settings can also
   be sampled, provided they do not change the solver layout or reset settings.
3. For moving sphere/box obstacles, enable **Moving colliders** before baking.
   Keep their size, shape and membership constant throughout the range.
4. Choose an absolute bake folder, or save the blend before using a relative one.
   Set First/Last frame, **Start empty**, and **Animated inputs**, then Bake New Cache.
5. Completion, cancellation and handled failure restore the original timeline
   frame and subframe. Select a completed integer frame, Load Cache, and scrub.

Each run gets its own folder. Cancellation retains completed frames. Cache playback
shows saved scalar fields without running fluid physics. It is still a viewport
preview, with no EEVEE/Cycles output or solver-resume capability.

## Timing and sampling

The first frame is the initial state at time zero. Frame `f` represents
`(f - first_frame) / (fps / fps_base)` simulated seconds. Keyframes are evaluated
at each integer destination frame. Emission rate, heat, source radius and other
sampled settings are held at that destination value for the preceding interval.
Emitter positions sweep between the two sampled endpoints; moving colliders
interpolate translation and shortest-path rotation between endpoints. This does
not evaluate the Blender animation curve at every fluid substep. Very fast or
curved motion needs more timeline samples. Cache playback has no subframe interpolation.

Collider motion is subdivided to at most half a grid cell per fluid step.
Motion requiring more than **2 m/s surface speed** in solver coordinates is
rejected instead of allowing the obstacle to lag behind its keyed frame.
Rotating boxes must meet this limit too. Start at 32³ for moving obstacles.

## Supported scope and invalidation

Direct keyframes use Blender 5.3's layered Action/channelbag API. Drivers, NLA,
tweak mode, active object constraints, sampled F-curves and F-curve modifiers
are rejected. Bake constraints to ordinary keys and remove the unsupported
animation setup before using this workflow. Moving/deforming mesh SDFs are not
supported; static mesh obstacles remain available with moving mode disabled.
Grid, initial state/solver modes, timestep controls, FPS and collider membership
must remain constant. Primitive scale changes, shear and mirrored transforms
are outside the moving-collider model.

The cache stores the direct animation definition and a fingerprint of evaluated
inputs for every completed frame. Changing an earlier key, its handles or
interpolation invalidates later cached frames even when their endpoint values
match. Current-frame setting edits also invalidate playback. Restoring matching
inputs restores usability. Object renames conservatively invalidate the cache.
Display controls and viewport orbit do not invalidate it. This is a restricted
direct-keyframe workflow, not a general dependency-graph history tracker.
Existing fixed-input caches retain their original fingerprint scheme.

## Validation

Tested 2026-09-29 on Apple M5 Pro / Metal, Blender 5.3.0 Alpha build
`b2e052b7172a`. **124 standalone tests and 82 Blender checks passed**:

- 20 animated GPU checks: frame timing, emitter size/rate/heat, moving box pose
  and mask, two bit-identical bakes with different processing budgets, playback,
  earlier-key invalidation, motion-control invalidation, cancel and speed rejection.
- 7 timer/handler checks: actual asynchronous bake, timeline restoration,
  scrubbing, cancellation and resource cleanup.
- 6 background Blender checks: signature/save-load persistence and rejection of
  constraints, drivers and NLA.
- 25 fixed-cache and 24 moving-collider regression checks.

Run `scripts/animation_validate.py` in graphical Blender after `scripts/dev_load.py`.
Run `scripts/animation_ui_validate.py` separately and wait for its asynchronous
report. `scripts/animation_cpu_validate.py` runs in background Blender. Reports
are preserved in [validation/animation026](validation/animation026).

Repeatability is verified on this build and device; bit-identical output across
other GPUs, drivers or Blender builds is not guaranteed. No new realtime speed
claim is made by this milestone.
