# Bake and timeline cache

FluxFX now bakes a chosen frame range to disk and displays those saved fields
when you scrub or play Blender's timeline. Playback does not run the fluid solver.
With **Animated inputs** disabled, baking evolves **fixed inputs sampled from the current scene**:
emitters, obstacles and simulation settings are held constant. Keyframed input
animation is not sampled. Moving-collider mode must be disabled; static analytical
and mesh SDF obstacles are supported. Version 0.26 adds an optional
[animated-input workflow](ANIMATED_BAKING.md) for direct keyframes and moving primitives.

## Use

1. Install `fluxfx-0.28.0.zip`. Configure the domain, sources, combustion and
   turbulence as usual. Stop on the scene frame whose input arrangement you want.
2. Expand **Bake and cache playback** at the top of the FluxFX sidebar.
3. Choose a **Bake folder** and **First frame / Last frame**. Save the `.blend`
   first if using the default relative folder `//fluxfx-cache/`; otherwise choose
   an absolute folder. The estimated disk requirement appears before baking.
4. Leave **Start empty** enabled to begin with zero smoke, heat and fuel. Disabling
   it uses the solver's seeded initial state. Baking always starts a fresh
   simulation; it does not continue the current live preview.
5. Click **Bake New Cache**. Progress counts completed frames. **Cancel Bake**
   stops at the next main-thread opportunity and preserves completed frame files.
6. The generated run folder appears in **Playback folder**. Click **Load Cache**,
   then scrub or play the Blender timeline within the baked range. Set the
   timeline's own start/end as desired; FluxFX does not alter them.
7. Use the existing Display selector for Density, Temperature, Fuel, Flame or
   Collision mask, where stored. Exposure, view mode and viewport orbit remain
   adjustable. **Release Cache** frees playback resources without deleting files.

Each bake receives a new `fluxfx-bake-…` subfolder. Previous bakes are never
replaced. The first cached frame is the initial state at simulation time zero;
frame `f` has time `(f - first_frame) / scene_fps`. The inclusive range is capped
at 10,000 frames. Frame rate includes Blender's FPS base. A 1–120 range at 24 fps
therefore ends at 119/24 seconds, not 120/24 seconds.

The output folder path and bake controls survive saving the `.blend`. Cache files
remain external and are not packed into it. Copy the run folder with the scene
when moving projects, select its new path, and Load Cache again. Loading a blend
or enabling the add-on does not automatically read files or start a bake.

## Stored fields and integrity

All caches store density and signed temperature excess. Combustion adds fuel and
flame/burn-rate; obstacles add their collision mask. Every field uses dense,
little-endian float32 storage without quantization. Version 0.27 adds optional
[lossless compression](CACHE_COMPRESSION.md); the default keeps raw storage. Version 0.28 adds a bounded [decoded-frame RAM pool](FRAME_MEMORY.md), default
256 MiB, and optional nearby-frame prefetch. The displayed CPU frame and temporary
decode buffers can use additional memory; GPU memory holds its displayed scalar texture.
Switching channels uploads from the loaded frame without disk access.

The disk estimate assumes raw storage even with compression enabled, because
savings depend on the evolving fields. Completion reports the actual frame payload
size. Compression is fixed for each run and does not affect input invalidation.

A versioned JSON manifest records grid shape/extent, frame rate/range, channel
order, input fingerprint, build provenance and completed frames. Each frame has
an exact byte count and CRC32 integrity check. CRC32 detects accidental damage;
it does not authenticate cache files. Metadata/input fingerprints use SHA-256.
The reader checks supported dimensions, frame sequence, field signs and finite
values. NumPy bundled with Blender accelerates bulk validation; the portable
format module also works without it.

Frames and the manifest are written through temporary files and atomic renames,
with file flush/fsync before publication. A frame is discoverable only after its
manifest entry is published. Cancellation/failure retains the completed prefix.
A process interruption can leave a run marked `BAKING`, a temporary file, or an
unlisted final frame; only listed, verified frames can be loaded. This is not a
resume mechanism or a guarantee against filesystem/hardware failure.

The preflight disk estimate includes raw fields plus per-frame and manifest
allowances. Disk exhaustion or other write errors stop the job and release GPU
resources; if the manifest cannot be updated, its previous published prefix
remains usable. FluxFX does not automatically delete old caches.

## Stale caches and lifecycle

On load and during playback, FluxFX compares the evaluated source geometry/jets,
additional emitters, collider geometry/transforms, simulation settings, grid,
FPS, initial-state choice and domain placement with the baked fingerprint.
A mismatch hides the volume and reports that the cache is outdated. Restoring
matching inputs makes it usable again. Unavailable source objects, missing frames
and corrupt frame files likewise hide the volume rather than showing an old
frame. Moving the timeline back to a valid frame recovers playback.

Display-only edits do not invalidate the cache. Changing the requested range or
output folder does not change an already loaded run's range. Input comparison
uses evaluated values, not the history of animation curves: animated scenes are
outside this fixed-input workflow and may become stale when scrubbed. Camera
orbit is independent of the simulation; moving the domain itself invalidates
this version's cache.

Baking, cached playback and live simulation are mutually exclusive. Reset/Play
starts the live workflow and releases cache playback. Undo, redo, file loading,
scene changes and disabling the add-on stop relevant timers and release resources.
Frame-change handlers only queue main-thread work; file reads and GPU uploads
occur in the timer. Rapid scrubbing coalesces to the latest requested integer
frame; subframe interpolation is not implemented.

## Measured M5 Pro performance

Blender 5.3.0 Alpha, build `b2e052b7172a`, Apple M5 Pro / Metal, 2026-09-28.
The test contains combustion, turbulence, an additional emitter and a static mesh
obstacle. All five scalar fields are stored; density is displayed. It repeats
reads twice immediately after baking, so these are **warm filesystem-cache
measurements**, not cold-disk or network-drive guarantees.

| Grid | Frames measured | Disk size | Median frame load | Maximum frame load |
| --- | --- | --- | --- | --- |
| 32³ | 12 | 7.50 MiB | 0.72 ms | 1.19 ms |
| 64³ | 12 | 60.00 MiB | 2.41 ms | 2.66 ms |
| 128³ | 4 | 160.00 MiB | 12.26 ms | 13.09 ms |

Load timing includes input validation, file read/checksum, all field validation,
selected-channel upload and a GPU texture readback to ensure completion. It
excludes viewport raymarch drawing and Blender UI scheduling. These load costs
fit within a 24/30 fps frame budget in this test, but do not establish full
viewport FPS. Five-channel storage for 120 frames is approximately 75 MiB at
32³, 600 MiB at 64³, and 4.69 GiB at 128³, plus manifest/filesystem overhead.

The bake loop uses a soft 20 ms compute budget per callback and writes at most one
frame per callback. A single GPU step, readback/write, or initial mesh SDF build
can exceed that budget. Cancellation cannot interrupt a GPU call or file write
already in progress. Bake performance depends on the fluid settings, unlike
cache playback; dense high-resolution files remain substantial.

## 0.42 bake data path

Baking no longer converts fields through Python lists. `BlenderGPUDevice.read_array`
returns a zero-copy float32 view of each `GPUTexture.read()` buffer (Blender's
`gpu.types.Buffer` exposes the Python buffer protocol), and `CacheWriter` validates,
checksums and writes that memory directly. RAW frames are byte-identical to 0.41;
compressed frames remain one standard zlib stream. Lists, `array('f')`, NumPy and
memoryview inputs are all accepted, and Blender builds without the buffer protocol
fall back to one explicit conversion. `BlenderGPUDevice.read` still returns a list
for diagnostics and validation scripts.

Five 128³ channels (40 MiB per frame), median per frame, measured in the Linux
cloud sandbox with Blender 5.2.2 as a Python module on a software OpenGL GPU
(llvmpipe). These are relative measurements, not M5 Pro timings:

| Stage | 0.41 | 0.42 |
| --- | ---: | ---: |
| Readback to CPU fields | 433 ms | 21 ms |
| Cache write (validate, CRC32, write, fsync) | 386 ms | 262 ms |

Inside the 0.42 write, validation takes about 5–10 ms and CRC32 about 10–13 ms;
the rest is file I/O on the sandbox filesystem (about 240 MB/s for new files).
Python-side copying is effectively gone; the remaining cost is integrity checking
and storage. Reproduce on the production machine in graphical Blender:
`scripts/bake_copy_benchmark.py` (see its docstring). Evidence:
[validation/bake_io_042](validation/bake_io_042).

## Scope and validation

These are **viewport playback caches**, not solver checkpoints: velocity,
pressure and solver history are omitted, so they cannot resume physics. The
existing collider-free fixed-step checkpoint API remains separate. There is no
OpenVDB export, EEVEE/Cycles integration, moving-mesh bake,
asynchronous disk streaming or wavelet upres in this release.

The 0.25 baseline passed 205 Blender checks and 123 standalone tests.
See the animated-input notes for 0.26 validation. Standalone coverage includes exact field roundtrip, negative heat,
partial cancellation, isolated runs, ordering, failed-write non-publication,
corrupt/truncated files, manifest validation and storage bounds. Blender tests
cover exact GPU/disk/GPU equality of all five channels, static mesh and multiple
source support, missing/corrupt frames, stale settings/FPS/colliders, live/cache
transitions, actual bake/cancel/load operators, actual timer-driven scrubbing,
undo/load/disable cleanup, and saved cache paths/settings.

Reproduce with `scripts/cache_validate.py` and `scripts/cache_ui_validate.py`
after `scripts/dev_load.py` in graphical Blender. The UI script is asynchronous;
wait for its report before starting another test. `scripts/source_save_validate.py`
checks `.blend` persistence in background Blender. Existing live UI, turbulence
and solver regression suites also pass. Reports are in
[validation/cache025](validation/cache025).
