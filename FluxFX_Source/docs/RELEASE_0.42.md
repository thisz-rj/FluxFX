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

### On the target: M5 Pro, Metal, Blender 5.3.0 Alpha (October 7)

The run is `exit_criteria_128_fire_120_frames`, run in-session from the source
tree. Full values are in [validation/mac_042](validation/mac_042/in_session_042.md).

| Result | Value |
| --- | --- |
| Bake | **120/120 frames in 107.6 s**, mean 897 ms per frame; cache and VDB complete |
| VDB vs cache | exact at frames 1, 60 and 120, all five grids; the Volume plays frames 1–120 |
| VDB | 0.712 GiB for 120 frames |
| Cycles (CPU, 320 px, 32 samples) | flame visible at frames 40, 80 and 120 (1357, 1349 and 1340 fire pixels) |
| Readback, median per frame | 3.53 ms, **0.39%** of a bake frame |
| Readback + cache write | 12.6 ms, **1.41%** of a bake frame (target < 15%) |
| VDB write, median | 45.6 ms, 5.1% of a bake frame |

| # | Exit criterion | Status |
| --- | --- | --- |
| 1 | 128³, 120-frame fire bake | Met on Metal (107.6 s) |
| 2 | Export to a renderable sequence | Met; exact against the cache |
| 3 | Cycles render | Met |
| 4 | Visible flame | Met: Cycles at 32³ and 128³, EEVEE at 32³ |
| 5 | Copy overhead < 15% of a bake frame | Met: 1.41% including cache write (0.41: 284–433 ms readback alone) |
| 6 | Idle cache does no expensive work | Met: 0 fingerprints in 300 ticks, 0.035 ms per tick on Metal |
| 7 | CI on every push | Met: four jobs, including headless Blender |
| 8 | Fixed-dt NaN detection | Met on Metal: NaN, Inf and 5e30 detected; poisoned bake stops |
| 9 | Existing tests pass | Met for the suites run: unit, native and CI headless. On Metal: `gpu_validate.py`, sparse/dense parity, `cache_ui_validate` 11/11 and `playback_validate`. In the sandbox: `cache_validate` 25/25, `frame_cache_validate` 23/23 and `compression_validate` 20/20. The other older graphical scripts were not rerun. |
| 10 | No sparse expansion | Met: no sparse or native engine changes |

### Earlier sandbox run (software OpenGL)

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

On llvmpipe the readback was 21 ms per 128³ frame, against 284–433 ms in 0.41.
The VDB write is optional per bake; it can be deferred with **Export VDB from Cache**.

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

- **Apple Silicon in-session suites (October 7, same machine):**
  - `headless_validate.py`: 10/10 PASS on Metal, including fire, VDB, Cycles
    and EEVEE flame, NaN/Inf injection and idle-cache checks;
  - the 128³ exit-criteria run: PASS;
  - `gpu_validate.py run_suite`: PASS.

  After the `capture()` compatibility fix, a fresh Blender reran
  `headless_validate.py` (10/10) and added the timer-driven older suites:
  `cache_ui_validate.py` 11/11 and `playback_validate.py` PASS.
  See [validation/mac_042](validation/mac_042/in_session_042.md).

- **Older graphical suites, rerun in the sandbox (bpy module, llvmpipe):**
  - `frame_cache_validate.py`: 23/23 PASS;
  - `compression_validate.py`: 20/20 PASS;
  - `cache_validate.py`: 25/25 PASS. Its live-session step needs a window, so
    the sandbox run bypassed the window-only GPU gate. Its checks include
    stale-on-edit, edit during bake, cancel, undo and file-load cleanup.

  These suites found one compatibility break, now fixed.
  `backend.cache.capture` had started returning zero-copy views instead of
  0.41's lists, which broke the suites' bit-exact comparisons. `capture` is
  back to lists, and bakes use the new `capture_views`. The baked bytes are
  unchanged.

## Reproducing the Mac validation

The package test above did not exercise combustion, renders, NaN/Inf injection,
idle-cache behaviour or the 128³ run; the in-session suites below covered them
on October 7. They run inside an already open Blender, with no extra process:
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

The two older suites that need Blender's timer loop (both passed on October 7)
cover the operator bake, cancel, scrubbing, disable cleanup, live timers and
edits, all paths that Phase 3 touched. They report by writing JSON to
`SRC/test-results/` after they finish:

```python
os.makedirs(SRC + '/test-results', exist_ok=True)
runpy.run_path(SRC + '/scripts/dev_load.py', run_name='fluxfx_dev_load')     # register from source
runpy.run_path(SRC + '/scripts/cache_ui_validate.py', run_name='v')['run']()  # about a minute, timers
# wait for it, then:
print(open(SRC + '/test-results/cache-ui-validation.json').read()[:3000])
runpy.run_path(SRC + '/scripts/playback_validate.py', run_name='v')['run']()  # turns this area into a 3D View until done
# afterwards:
print(open(SRC + '/test-results/playback-validation.json').read()[:3000])
import fluxfx; fluxfx.unregister()                                           # before re-enabling the installed add-on
```

Then by hand, with the installed add-on re-enabled (the suites render Cycles
on the CPU and do not click through the panel):
1. **Create Smoke Domain**, **Create Smoke Emitter**, **Use Basic Fire Settings**.
2. Set Grid 128³ and frames 1–120, then **Bake New Cache**.
3. Check that `FluxFX Render Volume` appears and that the timeline plays it
   together with the viewport preview.
4. Press F12 in Cycles with the Metal GPU, then in EEVEE.
5. Drag **Fire intensity**: the material should update live.
6. Leave the timeline idle and check Blender is near idle in Activity Monitor.

## Known limitations

- **Manual UI pass:** not yet done on the Mac, and neither is a Cycles render
  with the Metal GPU device (the suites render on the CPU).
- **No motion blur:** the cache does not store velocity, so no velocity grid
  is exported.
- **Main thread:** VDB and cache writing run on Blender's main thread;
  there is no asynchronous disk worker.
- **Fire defaults:** they were calibrated for the default 1 m domain. Emission
  scales with flame thickness, so adjust **Fire intensity** for other sizes.
  Temperature mode is physically literal and dim for the preset's ~900 K.
- **Guard cost on Metal:** at 64³ the guard takes 0.514 ms against the 0.41
  fence's 0.286 ms, adding 0.23 ms to a 2.3 ms step (about 10%). The 128³ bake
  still runs at 897 ms per frame. If that matters for live playback, the
  guard's 8-float result could be read one step late, or only once per frame
  in bakes. Not done in 0.42.
- **Duplicate root tree:** the repository root still holds the frozen 0.41
  add-on tree beside `FluxFX_Source/`, marked as a snapshot in the root
  README. Removing it was left to the maintainer.
