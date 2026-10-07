# FluxFX 0.18 — wall-clock playback

Play now consumes elapsed wall time through as many adaptive fluid steps as the
callback budget allows. This removes the previous one-step-per-timer slowdown.
The dense solver and pressure/advection algorithms are unchanged from 0.17.

## Controls and timing

- **Playback budget (ms)** defaults to 24. Lower it for more frequent UI yields;
  increase it to allow longer bursts. It is a soft limit: a GPU step already in
  progress cannot be interrupted. At most 32 steps run per callback.
- **Playback speed** is completed simulated seconds / elapsed wall seconds since
  the latest Play, including timer delays and time spent rendering between calls.
  It is a session average, not viewport FPS. 1× means keeping pace with wall time.
- **Callback** includes settings/source sampling, adaptive bounds, dispatch and
  GPU completion readback. It excludes the subsequent viewport draw.
- **Lag** is pending time plus time spent doing the current callback. Up to 250 ms
  is retained at the start of each callback. Lag can temporarily exceed that cap
  by the duration of the callback.
- **Skipped wall time** accumulates discarded debt. The fluid is never silently
  advanced over it. A slow scene therefore advances less simulated time, while
  remaining available for live edits. Sleep or a blocked UI does not cause an
  unbounded catch-up loop.

When caught up, the timer requests the remainder of a nominal 1/30-second cycle;
when behind, it requests a 1 ms yield. Blender decides when callbacks actually
run. These requested intervals are not scheduling guarantees. Pause preserves the
fluid, clears the pending clock and source history, and retains the last displayed
statistics. Play starts fresh timing. Step advances one adaptive step, independently
of wall time. Reset, release, undo, file loading and disabling clear owned resources.
Changing grid/initial-state settings or the active scene stops playback.

## Moving emitters and live edits

The current primary and additional emitters are sampled once per callback. Each
sampled path is divided across the adaptive steps, rather than emitting over the
entire path repeatedly. Only successfully consumed endpoints enter source history,
so an unfinished path can continue on the next callback. Source rates remain per
simulated second. Motion inheritance uses the pending simulation interval during
Play; manual Step retains its existing frame/max-step convention.

This is a live-preview approximation: it interpolates from the last consumed
position toward the latest evaluated object position, using the latest source and
flow settings. It does not record historical transforms or property changes during
lag. Dropped debt clears old paths, avoiding a long trail after a stall. Source
identity changes, disabling emission and timeline discontinuities retain their
existing trail-reset behavior. Timeline scrubbing is still not simulation seeking.

## Blender API boundary

A one-texel compute dependency on the completed density, temperature, velocity and
divergence textures is synchronously read back after each step. This adds four
bytes of texture storage and a small synchronization cost. It measures completed
work for budget decisions without downloading full fields. It is not a GPU timestamp
query, and its single sample is not a full-field numerical correctness test.
Python timer callbacks execute on Blender's main thread; there is no background
simulation worker and no way to preempt one long dispatch/readback. At 128³, one
step may itself exceed the requested budget. The viewport remains an unlit overlay
without scene-object occlusion or final-render integration.

## Validation

Validation passed: **82 standalone tests and 186 Blender checks** (125 solver
regressions, 36 playback checks, 19 UI/lifecycle checks and 6 save/load checks).
See `validation/playback018/` for saved reports. Reproduce with the standalone
unit suite, `scripts/playback_validate.py` in graphical Blender, the existing
`scripts/release017_validate.py` regression runner, and `scripts/ui_validate.py`.
The playback test uses temporary scenes, actual Blender timers and scene previews,
with a stationary source, moving object, two moving objects, live source/curl edits,
and deliberate 128³ overload. It restores the original scene without saving it.

Measurements are specific to the tested M5 Pro / Metal, Blender 5.3.0 Alpha build
b2e052b7172a. They are short interactive samples, not guaranteed realtime rates.

Measured four-second sessions (preview enabled; 24 ms budget at 64³):

| Scene | Grid | Simulation / wall time | Last lag | Skipped wall time |
|---|---|---:|---:|---:|
| stationary | 64³ | 0.981× | 75 ms | 0.00 s |
| moving | 64³ | 0.994× | 18 ms | 0.00 s |
| multiple | 64³ | 0.994× | 18 ms | 0.00 s |
| overload | 128³ | 0.192× | 275 ms | 2.97 s |

The 128³ case deliberately requests a 1 ms budget to exercise overload yielding.
It completes one step per callback; this is not a normal-budget 128³ performance
comparison. No 64³ session skipped wall time in this run.

## 0.42 invalid-value guard

The completed-step fence now also guards the simulation. After every step, in
fixed and adaptive timestep modes alike, density, temperature, the three face
velocities and (with combustion) fuel and flame are reduced on the GPU to their
largest magnitude with the existing `max_reduce` kernel; NaN and Inf map to a
sentinel. A small combine pass gathers the results, and one 8-float readback
replaces the previous 1-float fence read. The 0.41 fence sampled only voxel
(0, 0, 0), so fixed-step runs could continue with NaN elsewhere.

A NaN, an Inf or a magnitude of 1e30 or more stops playback, Step or Bake with a
message naming the fields, the step and the time. The solver is marked faulted:
it refuses further steps until Reset, and the viewport stops drawing its fields.
A failed bake keeps its completed frames and records the message in the cache
manifest; the bad frame is never written.

Headless Blender 5.2 (software OpenGL) checks inject NaN, Inf or 5e30 deep
inside each field and confirm detection. At 64³ the guard cost 2.3 ms against a
0.1 ms fence on that software GPU, about 1% of a step there.

On the M5 Pro (Metal, Blender 5.3.0 Alpha), the same 64³ check measured
0.514 ms for the guard against 0.286 ms for the 0.41 fence. That adds 0.23 ms
to a 2.3 ms step, about 10%. Reading the guard result one step late, or once
per frame in bakes, would remove most of it if needed. The 128³ Basic Fire
bake runs at 897 ms per frame with the guard on every step.

