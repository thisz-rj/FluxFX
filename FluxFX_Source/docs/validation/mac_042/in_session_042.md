# 0.42 in-session validation on Apple Silicon (October 7, 2026)

**Setup:**
- Apple M5 Pro, macOS 27.0.1 arm64, Blender 5.3.0 Alpha (`b2e052b7172a`), Metal backend.
- Suites ran in the Python Console of a running Blender, using `run_in_session` from the
  `claude-development` source tree (FluxFX `0.42.0`, normal `register()`, no version-gate
  bypass), with the installed add-on disabled.
- Values are transcribed from the console output; the JSON reports stayed on the Mac.

## `headless_validate.py`: 10/10 PASS

Cleanup: 20 temporary data-blocks removed; FluxFX unregistered.

| Check | Result |
| --- | --- |
| fixed_cache_playback_fingerprints_only_after_changes | 300 idle ticks, 0 fingerprints, 0.0349 ms per tick. First timeline pass 5, second pass 0; 0.41 needed 312 for the same ticks. |
| animated_cache_playback_fingerprints_once_per_frame | PASS |
| bake_does_not_refingerprint_every_tick | PASS |
| step_guard_detects_invalid_values_anywhere | NaN/Inf detected in density, temperature, velocity V and flame; 5e30 detected in velocity W. The 0.41 fence missed the interior NaN. Healthy maxima are identical to the llvmpipe run (density 0.9768, temperature 80.3301). |
| bake_stops_on_invalid_values | PASS |
| step_guard_cost (64³) | legacy fence 0.286 ms, guard 0.514 ms, step + guard 2.3 ms |
| fire_bake_writes_matching_vdb_sequence | 16 frames, exact. Scene frames 1/9/16/17 map to files 1/9/16/none. Five grids load. Flame max 0.7853, temperature max 884.5 K, VDB 1.2 MiB. Bake complete in 0.1 s. |
| export_from_existing_cache_matches | PASS |
| render_volume_cycles_smoke_and_fire | Flame mode: 81 fire pixels. Temperature mode: red gain 0.1294, 103 lit pixels against 94 smoke pixels (no ambient glow). Smoke only: no emission. |
| render_volume_eevee | rendered, 340 fire pixels |

The Cycles numbers match the Linux llvmpipe run almost exactly (81 fire pixels, means 0.1602, 0.1588
and 0.1587, 94 smoke pixels). Metal and OpenGL produce practically the same fields.

## Exit criteria: `-k exit_criteria`: PASS (109.4 s)

128³ Basic Fire, frames 1–120, VDB written during the bake. Cleanup: 10 temporary data-blocks removed.

| Measure | Value |
| --- | --- |
| Bake | 120 frames in 107.6 s, mean 897.0 ms per frame |
| Readback, median per frame | 3.53 ms, 0.39% of a frame |
| Cache write, median (validate, CRC32, write, fsync) | 9.09 ms; readback + write = **1.41%** of a frame (target < 15%) |
| VDB write, median | 45.62 ms, 5.1% of a frame |
| VDB | 0.712 GiB for 120 frames; exact against the cache at frames 1, 60 and 120 |
| Flame | max 0.8855 fuel/s; Cycles (CPU, 320 px) shows flame at frames 40, 80 and 120 (1357, 1349 and 1340 fire pixels) |

## `gpu_validate.py run_suite`: PASS

Run at 2026-10-07T07:39:35Z.

- **Diagnostics:** READY. METAL / APPLE / Apple M5 Pro, compute and image load/store available.
- **3D probe:** 105 texels, max error 0.0.
- **Advection against the CPU reference:**
  - zero velocity: 3.1e-7
  - translation: 7.9e-7
  - rotation + source + decay: 2.1e-6
  - decay only: 4.2e-7
- **Dense runs:** 64³ and 128³, 30 steps plus reset, PASS.
- **Registration:** register/unregister twice, PASS.

## Second session: after the `capture()` compatibility fix

The source tree for this session matches `e538890`, and the add-on code is identical at `0177b31`.
Blender was restarted with the installed add-on disabled.

- **`headless_validate.py`:** 10/10 PASS on Metal (normal `register()`). Cycles took 1.23 s
  and EEVEE 0.38 s. Cleanup removed 21 data-blocks.
- **`cache_ui_validate.py`:** 11/11 PASS, with operators and timers live:
  - start operator, timer bake complete, completed timer removed;
  - load operator, timer loads the last frame, timer scrubs backwards;
  - bake operator, cancel operator, cancel keeps partial frames, cancel timer removed;
  - disabling releases playback.
- **`playback_validate.py`:** PASS on Blender 5.3.0 Alpha. In the 64³ stationary case, 3.98 s
  was simulated in 4.01 s of wall time (speed 0.993) with a 24 ms budget and no dropped time.
  Observed callbacks took 10.7–11.7 ms at 2 substeps.

Not covered by these suites: Cycles with the Metal GPU device (the suites render on CPU) and the manual UI pass.
