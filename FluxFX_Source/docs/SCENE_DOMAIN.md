# Version 0.11 — scene-space domain and smoke preview

Smoke now renders at a scene position instead of only in a corner inset. The
solver is unchanged from 0.10. Tested on Apple M5 Pro / Metal, Blender 5.3.0 Alpha
b2e052b7172a, September 23, 2026 local time (September 22 UTC).

## Use

1. Open the FluxFX sidebar and click **Create Smoke Domain**.
2. Click **Reset**, then **Play**. **View → Scene volume** is the default.
3. Select the domain box and use numpad decimal to frame it. Orbit, pan, and zoom
   normally. Perspective and orthographic views both work.
4. Use G/R/S to move, rotate, and scale the domain. Existing smoke follows it
   without resetting or resampling simulation textures.
5. Pause or release the GPU preview as before. The domain object remains in the
   scene; it is not deleted by releasing the simulation or disabling the add-on.

The Domain picker also accepts an existing Empty. Newly created domains use a
cube Empty of display size 0.5, centred at world (0,0,0.5), so its initial box
spans one metre above the origin. Repeated Create reuses the assigned domain.
The renderer always interprets local [-0.5,0.5] as the box; changing an Empty's
**display size** is cosmetic. Use object **scale** to resize smoke placement.

The object and its transforms can be saved with the scene. Simulation textures
remain ephemeral; reopening requires Reset. Object motion is visual placement,
not moving-wall physics: density/temperature/velocity remain in the local unit
box, and buoyancy still points along its local +Z. Scaling the object does not
change cell size, CFL, physical domain extent, or optical depth in solver units.
It stretches the existing result. This stage does not create an object emitter.

## Rendering

A fullscreen GPU quad reconstructs near/far viewport rays by transforming clip
coordinates into domain coordinates with the inverse of the combined projection,
view, and domain transform. It intersects the ray segment with the unit box and
marches only the overlapping portion. This handles perspective, orthographic,
inside-volume views, near/far clipping, translation, rotation, nonuniform scale,
and mirrored transforms. Density is manually trilinearly sampled from the same
GPU textures used by the solver. No CPU field readback or extra volume texture
is added to normal rendering.

Premultiplied alpha blends smoke over the existing viewport; rays missing the
domain and empty density leave it unchanged. GPU blend/depth state is restored.
The former orthographic **3D inset** and **XZ slice** are still available.

A deleted/unassigned domain produces no scene smoke and a sidebar message. Hidden
objects skip rendering. A singular transform such as zero scale skips drawing
with a warning; restoring nonzero scale allows drawing again without resetting
physics. The draw path reads evaluated object transforms, including parenting.

## Explicit limits

This is a viewport **overlay**, with no scene-depth occlusion: smoke can draw over
objects that should be in front of it. No lighting, shadows, scattering, final
render-engine output, collisions, or multiple active domains. The scene-space
preview follows the viewport camera; it is not a registered Blender Volume
object. Domain transformations do not participate in fluid physics.

Full scene rendering can cost more than the earlier 260-pixel inset, especially
when the domain fills a large viewport. Previous inset benchmarks do not establish
scene-space frame rate. 64/128/256 ray samples remain available. Lighting and
correct scene-depth compositing are follow-up work, not claimed by this release.

## Validation

- **58 existing standalone tests pass**; physics is unchanged.
- **15 scene GPU/domain cases pass**, including perspective, orthographic,
  moved/rotated/scaled domain, camera inside, domain behind camera, mirrored
  transform, empty-volume compositing, domain reuse and transform preservation,
  and singular-scale rejection. Camera cases test 64 and 128 ray samples at
  five framebuffer positions each. Constant-density pixels match an independent
  CPU ray/absorption oracle within 3e-5 (maximum observed below 2e-6).
- **18 inset rendering cases pass** after extracting shared trilinear sampling.
- **17 UI/lifecycle checks pass**, including creation and release of the scene
  preview shader alongside the existing preview and solver resources.
- The actual smoke volume and selectable cube domain were visually inspected in
  Blender, framed in the viewport. The demo is left paused and unsaved.

[Scene checks](validation/m5-pro-scene-011.json) ·
[Inset regression](validation/m5-pro-inset-011.json) ·
[UI checks](validation/m5-pro-ui-011.json).

Run `scripts/scene_validate.py` through `runpy` with `run_name='__main__'` after
loading the source add-on in graphical Blender. It temporarily creates its own
domain, removes that test object, and restores the prior domain pointer. As with
other validation scripts, it rebuilds/releases the active GPU session.
