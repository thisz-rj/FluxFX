# Version 0.12 — object-controlled emitters

Historical milestone notes. Version 0.13 adds [motion, jets, and continuous trails](EMITTER_MOTION.md).

A single spherical source can now follow a Blender Empty. The numerical kernels
and pressure solver are unchanged. Tested in Blender 5.3.0 Alpha b2e052b7172a,
Apple M5 Pro / Metal, September 23, 2026.

## Workflow

In the FluxFX Source section, click **Create Smoke Emitter**. A sphere Empty is
created at the current manual source position and radius, parented to the domain.
A domain is created if needed. Repeating the action reuses the assigned emitter.
Source control switches to Object mode and the emitter is selected.

Use **G** to position it and uniform **S** to resize it, including while FluxFX
plays. New emission follows the next evaluated transform. Already emitted smoke
continues evolving in the domain. Density/heat rates and the emission checkbox
remain in the sidebar. Turn emission off to stop adding both scalars. Choose
**Manual** to return to numeric position/radius controls without resetting fields.
An existing Empty may also be assigned with the picker.

Uniform scale gives the expected spherical source. With nonuniform scale, the
source remains spherical and uses the largest transformed axis length as radius;
it does not become an ellipsoid. Empty display size is cosmetic: the created
sphere has display size 1 and object scale equal to the initial radius. Adjust
object scale rather than display size. Unparented existing Empties work through
the same world-to-domain mapping.

## Coordinates, animation, and lifecycle

`blender/emitter.py` reads evaluated transforms and computes
`relative = inverse(domain_world) * emitter_world`. Source position is relative
translation plus (0.5,0.5,0.5), and radius is the largest column length of the
relative 3×3 transform. Thus a parented source keeps its local position and size
when the domain moves, rotates, or scales. Physics still operates in the local
unit box; this is not moving-boundary physics.

Object mode supplies the existing live `source_center` and `source_radius`
settings, so it does not reallocate or reset GPU fields. Evaluated keyframes and
constraints can supply transforms. FluxFX playback remains independent of the
Blender timeline: it samples the current evaluated position, does not advance the
timeline, and does not seek/bake smoke when the timeline changes. Moving quickly
between sampled positions does not create an interpolated swept source path.

Sources outside the domain are not clamped to a wall. Only their overlap with
the box emits; a completely disjoint source emits nothing. Hiding an emitter's
viewport helper does not turn emission off; use **Emit smoke and heat**.

A missing/unlinked emitter or domain, nonfinite transform, or zero emitter size
causes an explicit error and pauses playback before stepping. It does not silently
fall back to the old manual source. Fix the object or choose Manual, then Play
again. A zero-scale domain cannot be inverted and also pauses. Reset still seeds
initial density/temperature at the current source even if continuous emission is
off, consistent with previous releases.

The domain and emitter are scene objects and can be saved in `.blend` files.
Release Preview or disable frees GPU state while keeping these objects. Object
creation supports Blender undo; existing undo cleanup releases the GPU session.

## Validation

58 existing standalone tests pass; no physics/shader changes were needed.
11 Blender/GPU checks pass for creation/reuse, transformed parenting, live move
and resize without reset, analytic density and heat injection, emission off,
nonuniform scale policy, evaluated keyframes, zero-size rejection, missing-emitter
pause, and retained Manual mode. Injection checks isolate a stationary 16³ field
with forces/decay disabled; density error stays below 2e-6 and heat below 2e-5.
All 17 UI/lifecycle regression checks also pass.

[Emitter evidence](validation/m5-pro-emitter-012.json) ·
[UI evidence](validation/m5-pro-ui-012.json).

Run `scripts/emitter_validate.py` through `runpy` with `run_name='__main__'` after
loading the source add-on. The script creates temporary objects, checks GPU data,
removes its fixtures, restores the prior settings/frame, and releases GPU state.

## Limits

One spherical Empty-controlled source. No mesh voxelization, multiple emitters,
velocity inheritance, collisions, timeline cache, or new real-time performance
claim. Scene lighting and object occlusion remain pending from 0.11.
