# 0.22 — Dense fuel combustion prototype

## Try it

Install `fluxfx-0.22.0.zip`. Create a smoke domain, choose 32³ in Grid and initial
state, then open **Combustion → Use Basic Fire Settings → Play**. The preset resets
the simulation and replaces primary fuel/heat, combustion, cooling and lift values.
It starts with empty fields, emits fuel at 1 unit/s and heat at 1000 K/s, and sets
direct smoke emission to zero so smoke is produced by burning. It leaves your
emitter geometry, additional emitters and colliders in place.

The preset selects **Flame**. Switch Display to Density, Temperature or Fuel to
inspect the other fields. Flame colours are an approximate orange/yellow mapping
of the last step's consumed fuel per second, not a temperature/blackbody shader.
Smoke and flame are separate preview channels in this release. The preview still
has no scene occlusion, lighting, or EEVEE/Cycles output.

Each primary/additional spherical emitter has a Fuel source /s control. Emission
Enabled controls fuel as well as smoke/heat. Existing fuel continues to burn after
emission stops while hot enough. Burn rate, ignition, yields and source rates can
change live. Enabling/disabling combustion requires Reset. Fuel/flame display is
blank with an explanatory label until combustion has been initialized.

## Model

Fuel is a nonnegative, dimensionless concentration transported with the same
Fast/Detailed scalar method as smoke. It has no independent dissipation. Signed
temperature remains kelvin excess above ambient; ignition 150 means **150 K above
ambient**, not an absolute temperature of 150 K.

After transport, source injection and cooling, a cell at or above ignition consumes
`fuel * (1 - exp(-burn_rate * dt))`. That amount is subtracted from fuel and multiplied
by Heat per fuel and Smoke per fuel to update temperature and density. The Flame
field stores consumed fuel divided by dt. New reaction heat drives buoyancy on the
following step. Adaptive stepping observes that temperature before the next velocity
update. The local decay law is bounded, but the coupled transport/ignition calculation
still has timestep and grid dependence. A fixed timestep is a reproducibility tool,
not a guarantee that arbitrary forces or resolutions are stable.

The method assumes unlimited oxidizer. There is no oxygen transport, detailed
chemistry, radiation loss, flame-front tracking, pressure expansion or detonation.
Cooling is exponential. This is artistic smoke/fire research, not a physical
combustion safety model. The closed domain accumulates hot fluid near its ceiling.

Static and moving voxel colliders exclude fuel; covered/newly uncovered moving
cells lose fuel just as they lose smoke/heat. Additional storage when enabled is
three R32F cell fields (two fuel buffers plus burn rate): 3 MiB at 64³, 24 MiB at
128³, excluding driver overhead. Disabled combustion allocates none of these.

## First cache foundation

`fluxfx.backend.checkpoint` provides `advance_fixed`, `save_checkpoint`, and
`load_checkpoint` for scripts running in graphical Blender. NumPy ships with this
Blender build; no external package install is needed.

```python
from fluxfx.backend.checkpoint import advance_fixed, save_checkpoint, load_checkpoint
advance_fixed(solver, 120, 1/120)  # identical input settings for every step
save_checkpoint(solver, "/absolute/path/fire.npz")
resumed = load_checkpoint("/absolute/path/fire.npz")
advance_fixed(resumed, 120, 1/120)
# Close both solvers when finished.
```

Format v1 stores grid/settings, simulation clock, density, temperature, fuel,
burning rate, MAC velocities and the pressure guess/previous timestep. Loading
creates a new solver and recomputes diagnostic divergence on its next step. Files
contain arrays and JSON, never pickled Python objects; writes replace the destination
only after completing a temporary file. Saving reads fields back and blocks.

This initial API rejects colliders and faulted sessions. It does not serialize
Blender objects, source-motion histories, live UI runtime, input animation, timeline
frames or preview settings. Supply the same source sequence after resuming; multi-
source tables are rebuilt from those inputs. Interactive wall-clock playback is
not deterministic. Tests establish matching fixed-input replay/resume on the tested
build and device, not bitwise portability across drivers or future versions. Full
cache UI, scrubbing, eviction and volume export remain later milestones.

## Measurements and validation

Apple M5 Pro / Metal, Blender 5.3.0 Alpha `b2e052b7172a`, tested 2026-09-28. Four
simulated seconds of the Basic Fire source, Detailed scalar/velocity transport,
Auto pressure, adaptive steps and completed-GPU fences. Compilation is warmed up;
viewport rendering and checkpoint I/O are excluded from timings.

| Grid | Simulated seconds / wall second | Median 1/30 s frame | p95 |
|---|---:|---:|---:|
| 32³ | 3.30 | 11.71 ms | 13.66 ms |
| 64³ | 0.625 | 71.56 ms | 78.18 ms |

64³ is **below realtime in this fire scene**. Heat produces faster flow and more
adaptive substeps; smoke-only or mild moving-wall timings are not interchangeable.
These runs verified finite fields, nonnegative fuel/density and active burning.

Validation covers analytic fuel decay, ignition, yields, extinguishing at zero burn
rate, Fast/Detailed transport, additive sources, emission-off behavior, static/moving
collider exclusion, fixed-input replay, checkpoint resume, preset/live UI controls,
save/load persistence and flame pixel oracles. Existing pressure, emitter, smoke,
collision and scene-volume regression suites also pass. Raw reports are in
[validation/combustion022](validation/combustion022).

Reproduce with `scripts/combustion_validate.py`, `scripts/combustion_ui_validate.py`
(asynchronous), and `scripts/combustion_benchmark.py` after `scripts/dev_load.py` in
graphical Blender. Pure numerical checks: `python3 -m unittest discover -s tests -q`.
