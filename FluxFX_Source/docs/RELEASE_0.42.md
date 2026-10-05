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
- **Not yet run on Apple Silicon:** Metal and Blender 5.3, which are the
  shipping targets (see below).

## Validation still required on the Mac (M5 Pro, Blender 5.3)

Run each step from `FluxFX_Source/`. The `blender` placeholder in these
commands is the Blender 5.3 binary, `"/Applications/Blender 2.app/Contents/MacOS/Blender"`.

1. **Unit and native tests:**

   ```sh
   python3 scripts/ci_checks.py
   ```

   Expect `All checks passed`.
2. **Package:**

   ```sh
   python3 scripts/package.py --out-dir dist
   ```

   This builds `dist/fluxfx-0.42.0.zip`. Install it with
   **Preferences → Add-ons → Install from Disk**, after removing 0.41.
3. **Existing GPU suite (graphical; covers Metal):**

   ```sh
   blender --factory-startup --python scripts/gpu_validate.py -- --output test-results/gpu-validation.json
   ```

   Check `"status": "PASS"`.
4. **0.42 checks on Metal:**

   ```sh
   blender --background --factory-startup --python scripts/headless_validate.py -- \
     --output test-results/headless-042.json --workdir test-results/headless-042
   ```

   Expect `Headless validation: PASS`, and look at the PNGs in
   `test-results/headless-042`. If `gpu.init()` fails in background mode,
   run the same command without `--background`.
5. **Copy overhead on the real GPU (graphical; quit Blender afterwards):**

   ```sh
   blender --factory-startup --python scripts/bake_copy_benchmark.py -- --grid 128 --output test-results/bake-io-042.json
   ```

   Compare `fast.readback_ms` (the copy) and `fast.write_ms` (CRC32 plus disk)
   with the bake's per-frame time from step 6.
6. **Production check, by hand:**
   1. New scene → FluxFX panel → **Create Smoke Domain**,
      **Create Smoke Emitter**, **Use Basic Fire Settings**.
   2. Set Grid 128³ and cache frames 1–120.
   3. Click **Bake New Cache**. The completion message reports total time;
      divide it by 120 for the per-frame time.
   4. Check that `FluxFX Render Volume` appears.
   5. Scrub the timeline: the viewport preview and the Volume must both play.
   6. Press F12 in Cycles (Metal GPU) at frames 40, 80 and 120: smoke and
      orange flame should be visible.
   7. Switch to EEVEE and press F12.
   8. Change Fire intensity and Flame temperature; the material should update
      live.
   9. Leave the timeline idle with the cache loaded: Activity Monitor should
      show Blender near idle.
The invalid-value guard is exercised on Metal by step 4: it injects NaN/Inf
into live GPU fields and runs a poisoned bake.

## Known limitations

- **Not validated on the shipping target:** validation ran on Linux with
  software OpenGL. Metal, Apple GPU timings and Blender 5.3 have not been run
  (Blender 5.3 is above the bpy wheel available here; the harness bypasses
  the 5.3 version gate on 5.2).
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
