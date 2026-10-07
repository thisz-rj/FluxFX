# FluxFX 0.42.0 — render-ready dense pipeline

0.42 turns the dense GPU solver's bakes into renderable assets. It removes the
bake and playback overheads identified in the 0.41 audit and closes the
fixed-timestep invalid-value gap. The sparse/native engine is unchanged, and
the dense solver's mathematics are untouched.

## What changed

| Phase | Change | Evidence |
| --- | --- | --- |
| 1 | `FluxFX_Source/` is the canonical tree. The version comes from `blender_manifest.toml`. The native core is a provenance-verified artifact (`prebuilt/macos-arm64` plus SHA-256 of the binary and its 16 build inputs). CI runs on every push. | CI matrix: Python 3.11, 3.13, 3.13 + NumPy |
| 2 | Bake readback and cache writing are zero-copy (buffer protocol, no Python lists). RAW cache files are byte-identical to 0.41. | 128³ × 5 channels: readback 284–433 → 21 ms per frame |
| 3 | Cache validation fingerprints inputs only after something may have changed (depsgraph IDs + FluxFX property key, memoised per frame). | Same tick sequence: 0 idle fingerprints vs 312 in 0.41 |
| 4 | Every step reduces all fields to their maximum magnitude, fixed-dt included. NaN, Inf or \|v\| ≥ 1e30 stops the solver and the bake. | Injected interior NaN/Inf/5e30 detected; the 0.41 fence missed them |
| 5 | OpenVDB sequence export, Blender Volume object and Principled Volume smoke/fire material for Cycles and EEVEE. | Exact cache equality; Cycles and EEVEE renders with visible fire |
| CI | A headless Blender job (bpy 5.2.2 on Mesa llvmpipe) runs the GPU bake, cache, guard, VDB and render checks on every push. | `headless-blender` job |

Details:
- [caching (Phases 2–3)](CACHING.md);
- [invalid-value guard](PLAYBACK.md#042-invalid-value-guard);
- [render export](RENDER_EXPORT.md);
- [API findings](API_LIMITATIONS.md#042-render-export).

## Exit-criteria run: 128³ fire, 120 frames

Basic Fire preset at 128³, frames 1–120, with **Write VDB for rendering** on.
The run used the real bake timer path and headless Blender 5.2.2 bpy on
llvmpipe (software OpenGL, 4 CPU cores).

| Result | Value |
| --- | --- |
| Frames baked | **107 of 120**. The sandbox stopped the job at its 2-hour limit while it was still healthy, leaving the cache (`BAKING`) and VDB (`EXPORTING`) as valid 107-frame prefixes. |
| Bake frame time (llvmpipe) | 6.4 s (frames 1–10) rising to 92 s (frames 98–107) as adaptive substeps follow the accelerating plume |
| Cache | 32.0 MiB per frame |
| VDB | 628.7 MiB for 107 frames; 12.4 MiB at frame 107 |
| VDB vs cache | max \|difference\| **0.0** for all five grids at frames 1, 54 and 107 |
| VDB write, largest frames | median 156 ms per frame: transposition 57, `copyFromArray` 22, OpenVDB write 81 |
| Render volume | `frame_start` 1, `frame_duration` 107, parented to the domain, `FluxFX Smoke and Fire` material |
| Cycles (CPU, 320 px, 32 samples) | frames 40, 80 and 107 under AgX, plus 107 under Standard: 3.0–3.3 s each, flame visible in every frame (1348–1432 fire pixels) |
| Value ranges | flame ≤ 0.882 fuel/s, temperature ≤ 915 K, density ≤ 0.445 |

The renders show:
- an orange flame column at the emitter;
- grey smoke spreading under the closed domain's ceiling.

The Basic Fire preset is laminar; turbulence controls the look.

**Copy overhead.**
- The Python-side conversion is gone. What remains per 128³ frame (five
  channels, 40 MiB) is one GPU→host transfer per field through Blender's
  `GPUTexture.read`: 21 ms on llvmpipe, against 284–433 ms in 0.41.
- On llvmpipe that is 0.02–0.3% of the bake frame time.
- That fraction is not representative of the M5 Pro. A 128³ multigrid
  step there is about 20 ms ([multigrid](MULTIGRID.md)), so the share
  depends on the substeps per frame and on Metal's readback speed.
- Mac step 5 below measures both. If readback plus storage exceeds 15% of a
  frame, the next step is moving CRC32 and file writes to a background
  thread; the zero-copy views already allow this.
- The VDB write (156 ms here) is optional per bake. It can be deferred with
  **Export VDB from Cache**.

**Remaining to finish on the Mac:** the full 120-frame run, which on Metal
should take minutes rather than hours.

## Validation summary

- **Unit suite:** 186 tests, standalone, Python 3.11 and 3.13, with and
  without NumPy.
- **Native CPU tests:** arena, bricks, regions, built with
  `-Wall -Wextra -Werror`.
- **Headless Blender 5.2.2:** 10 checks: idle/fixed/animated fingerprinting,
  bake fingerprinting, guard detection, bake fault stop, guard cost, VDB
  bake export, export from cache, Cycles render, EEVEE render.
- **Apple Silicon package test (October 7, Blender 5.3.0 Alpha b2e052b7172a,
  M5 Pro, Metal):** PASS for 7 targeted checks on `fluxfx-0.42.0.zip`
  (SHA-256 `5714c6aa…a7292`, identical to a build of `b6e0102`). See
  [validation/mac_042](validation/mac_042/README.md). Covered:
  - registration of all 30 classes;
  - Metal compute and image load/store probe;
  - packaged native Metal module (65,536 elements, no mismatches);
  - 12 dense 32³ steps with finite, non-negative density and reduced
    divergence (the new invalid-value guard ran every step without a false
    positive);
  - one-frame VDB export and volume creation (density, heat, temperature);
  - native sparse/dense parity;
  - clean unregistration.

## Validation still required on the Mac (M5 Pro, Blender 5.3)

The package test did not exercise combustion, any Cycles or EEVEE render on
Metal, the invalid-value guard with injected NaN/Inf, idle-cache behaviour,
long cache sequences, or the 128³ exit-criteria run. All of it runs inside an
already open Blender, with no extra process:
1. Disable the installed FluxFX add-on (Preferences → Add-ons). The suites
   register FluxFX from the source tree and unregister it again.
2. Run the steps below in the Python Console.
3. Re-enable the add-on afterwards.

The 0.42 suites never reset the file: they work in a temporary scene and
remove everything they create.

```python
import runpy
SRC = '/absolute/path/to/FluxFX_Source'
suite = runpy.run_path(SRC + '/scripts/headless_validate.py', run_name='fluxfx_validation')

# 1. The 10 checks CI runs on llvmpipe, now on Metal (about a minute).
#    Covers fire bake + exact VDB, Cycles/EEVEE flame renders, idle and bake
#    fingerprinting, NaN/Inf injection and the poisoned-bake stop.
r1 = suite['run_in_session']('--output', '/tmp/fluxfx-042.json', '--workdir', '/tmp/fluxfx-042')

# 2. Exit criteria: 128^3 Basic Fire, 120 frames with VDB, exactness at
#    frames 1/60/120, Cycles flame at 40/80/120, and per-frame readback and
#    cache-write share of bake time. Needs about 5 GiB in --workdir.
r2 = suite['run_in_session']('-k', 'exit_criteria', '--output', '/tmp/fluxfx-042-exit.json',
                             '--workdir', '/tmp/fluxfx-042-exit')

# 3. Existing regression suite (registers and unregisters FluxFX itself).
gpu = runpy.run_path(SRC + '/scripts/gpu_validate.py', run_name='fluxfx_validation')
r3 = gpu['run_suite']()
```

Pass criteria:
- `r1['status']` and `r2['status']` are `'PASS'`, and `r3` reports PASS.
- The PNGs in the work folders show smoke and orange flame.
- From `r2['checks']['exit_criteria_128_fire_120_frames']['details']`,
  `readback_and_cache_write_share` must be below 0.15 to meet the copy-overhead
  target. Above that, the follow-up is moving CRC32 and file writes to a
  background thread.

From a terminal, the same suites run as
`blender --background --factory-startup --python scripts/headless_validate.py -- [--full] --output …`.
If `gpu.init()` fails in background mode, drop `--background`.

Then a short hands-on pass with the installed add-on re-enabled:
1. **Create Smoke Domain**, **Create Smoke Emitter**, **Use Basic Fire Settings**.
2. Set Grid 128³ and frames 1–120, then **Bake New Cache**.
3. Check that `FluxFX Render Volume` appears and that the timeline plays it
   together with the viewport preview.
4. Press F12 in Cycles with the Metal GPU, then in EEVEE.
5. Drag **Fire intensity**: the material should update live.
6. Leave the timeline idle and check Blender is near idle in Activity Monitor.

## Known limitations

- **Only partly validated on the shipping target:** the Blender 5.3 / Metal
  package test covered registration, solver steps, single-frame VDB export
  and parity. Fire renders, guard injection, the 128³ run and Apple GPU
  timings on Metal are still open (see above).
- **No motion blur:** the cache does not store velocity, so no velocity grid
  is exported.
- **Main thread:** VDB and cache writing run on Blender's main thread;
  there is no asynchronous disk worker.
- **Fire defaults:** they were calibrated for the default 1 m domain. Emission
  scales with flame thickness, so adjust **Fire intensity** for other sizes.
  Temperature mode is physically literal and dim for the preset's ~900 K.
- **Guard cost:** one extra reduction chain per step (2.3 ms vs 0.1 ms at 64³
  on llvmpipe, about 1% of a step there). It is not yet measured on Metal.
- **Duplicate root tree:** the repository root still holds the frozen 0.41
  add-on tree beside `FluxFX_Source/`, marked as a snapshot in the root
  README. Removing it was left to the maintainer.
