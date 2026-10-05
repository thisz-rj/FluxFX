# 0.28 — Frame memory and prefetch

FluxFX now retains decoded cache frames in RAM to make revisiting frames faster.
In **Bake and cache playback**, choose **Frame memory (MiB)** (default 256) and
**Prefetch nearby frames** (default enabled), then Load Cache. Both controls can
change during playback and survive saving/reopening the blend. They do not alter
simulation fingerprints or existing files. Raw and losslessly compressed caches
are supported.

The pool evicts the least recently accessed frame when full. Prefetch reads up
to two frames ahead in the most recently observed scrub direction, leaving room
for the displayed frame. It also fills nearby frames while paused. A pool that
cannot hold two frames does no prefetch; zero disables retention and prefetch.
Reducing the limit evicts entries on the next playback/prefetch callback.
Release Cache, live Reset/Play, undo/redo, file loading, scene changes and add-on
disable clear the pool and remove playback/prefetch timers.

## What the memory limit covers

The limit covers **retained decoded float32 field payloads**, not all Blender
memory. A five-channel 128³ frame uses 40 MiB, so 256 MiB holds six such frames
(240 MiB). A five-channel 64³ frame uses 5 MiB. Python container overhead, the
currently displayed CPU frame if evicted from the pool, one displayed GPU texture,
encoded bytes and temporary decode buffers are additional. The pool shares its
arrays with the display adapter instead of duplicating the field data on hits.
Frame memory is transient and is never saved in the blend.

## Scheduling and integrity

Prefetch is cooperative work on Blender's main thread: one file read and decode
per callback. It does not use background Python threads or overlap GPU work with
I/O. A new frame handler cancels pending prefetch and queues the latest frame;
rapid scrubbing coalesces rather than uploading every intermediate request.
An already running read cannot be interrupted. Turn prefetch off if ahead reads
make interaction less responsive on a slow drive or a large compressed cache.

Each RAM lookup checks file identity, size and modification/change timestamps.
Changed files are decoded and validated again; missing/corrupt requested files
clear the displayed frame. The current frame is checked even while paused.
A failed speculative read does not hide a valid displayed frame. Input/animation
fingerprints are still checked before display, and mismatches clear the pool.
RAM entries belong to a single loaded run; Release/Load starts a fresh pool.
The loaded manifest is a snapshot: reload after externally replacing a manifest
or adding frames to a partial run. File metadata checks are accidental-change
protection, not file authentication.

## Measurements

Apple M5 Pro / Metal, Blender 5.3.0 Alpha build `b2e052b7172a`, 2026-10-02.
Four compressed frames with five fields, combustion and a static box were baked,
then read twice with retention disabled and twice after filling a 256 MiB pool.
The filesystem was warm. Prefetch was disabled for these timings to isolate RAM
retention. Each sample includes input fingerprinting, field preparation, density
upload and a GPU readback to ensure completion; viewport drawing and UI scheduling
are excluded.

| Grid | Disk/decode median | RAM-hit median | RAM-hit maximum |
| --- | --- | --- | --- |
| 64³ | 4.33 ms | 0.99 ms | 1.24 ms |
| 128³ | 27.66 ms | 7.54 ms | 9.28 ms |

These measurements show faster revisits/RAM hits, not a full viewport FPS result.
Prefetch moves read/decode work earlier; it does not remove its cost on the first
pass through a long sequence. Fast scrubbing may outrun it, and a long sequence
may exceed the pool. Disk misses retain the previous synchronous read path.

The sidebar reports whether the last requested frame was a **RAM hit** or a
**disk read**, the retained payload size/frame count, and the last prefetch time.
**Last frame CPU work** measures main-thread preparation and GPU submission; it
does not force GPU completion and should not be treated as rendered-frame time.
Prefetch timing covers file read/decode only. Both are separate from solver speed.

## Validation

**146 standalone tests and 89 Blender checks passed**: 23 frame-pool/GPU checks,
25 fixed-cache regressions, 20 compressed animated-bake checks, 8 asynchronous
animation/prefetch/scrub/cancel checks, and 13 save/load checks. Coverage includes
LRU eviction, strict payload limits, zero/undersized limits, exact cached values,
changed/deleted files, a file changing during decode, speculative failures,
reverse direction, rapid scrub coalescing, actual timer prefetch and cleanup.

Run `scripts/frame_cache_validate.py` after `scripts/dev_load.py` in graphical
Blender. The animation UI test is asynchronous; wait for its report before other
tests. Run standalone tests with `python3 -m unittest discover -s tests -q`.
Reports are in [validation/frame_memory028](validation/frame_memory028).
