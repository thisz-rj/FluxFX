# 0.27 — Lossless cache compression

Enable **Lossless compression** in **Bake and cache playback**, then Bake New Cache.
The setting defaults to off. It works with fixed inputs and animated-input bakes.
Load Cache detects the stored encoding automatically. The choice survives saving
and reopening the blend file. Changing the checkbox does not invalidate a loaded
run; it affects future bakes. Completion reports actual frame payload size.

## Storage and compatibility

Compression uses standard-library zlib at its fast level, preserving the exact
little-endian float32 bytes of every channel. If a compressed frame would be
larger, that frame is stored raw. There is no quantization. Fields include signed
temperature, density, optional fuel/flame and collision mask.

Raw bakes retain the original `fluxfx-playback-1` format. Compressed bakes use
`fluxfx-playback-2`, with per-frame encoding, stored byte count, decoded byte count
and CRC32 of the decoded data. Version 0.27 reads both formats; older add-ons do
not read compressed runs. Atomic file/manifest publication and partial-cache
cancellation behavior are retained. CRC32 detects accidental corruption; it does
not authenticate files.

The reader bounds the encoded read to the declared field size and bounds
decompression before allocating decoded fields. It rejects wrong sizes, invalid
encodings, truncated streams, excess decoded data, trailing/concatenated streams,
checksum mismatches and invalid field values. No compression package is installed.

The preflight estimate remains a conservative raw-storage estimate. Compression
is data dependent and cannot promise a fixed reduction. Per-frame encoded payloads
never exceed raw size; metadata and filesystem overhead remain additional.
Encoding assembles a full frame and compresses it in CPU memory, so temporary
memory can include two additional frame-sized buffers plus channel scratch and
codec overhead. A five-channel 128³ raw frame is 40 MiB. The simulation remains dense.

## Measured M5 Pro tradeoffs

Tested 2026-10-02, Blender 5.3.0 Alpha build `b2e052b7172a`, Apple M5 Pro / Metal.
Each case contains eight frames, combustion, turbulence, an additional emitter
and a static box obstacle. Raw and compressed bakes produced matching decoded
checksums on every frame; the last frame matched all five fields bit for bit,
including the GPU upload roundtrip.

| Grid | Raw frames | Compressed frames | Median raw load/upload | Median compressed load/upload |
| --- | --- | --- | --- | --- |
| 32³ | 5.00 MiB | 0.178 MiB | 0.60 ms | 0.87 ms |
| 64³ | 40.00 MiB | 0.710 MiB | 1.81 ms | 4.39 ms |
| 128³ | 320.00 MiB | 3.867 MiB | 13.98 ms | 29.27 ms |

These are short, mostly empty fields, including the initial empty frame; they
compress particularly well. Filled, turbulent fields may save substantially less.
Sizes above are frame payloads, excluding manifests and filesystem overhead.
Reads repeat twice immediately after baking and therefore measure warm filesystem
cache. Timing includes read, decompression, integrity/field validation, density
upload and a GPU readback for completion. It excludes animation fingerprinting,
viewport drawing and Blender UI scheduling. It does not establish full viewport FPS.

Raw/compressed bake times were 0.20/0.15 s at 32³, 0.73/0.76 s at 64³ and
5.66/5.86 s at 128³. These single runs include solver initialization, simulation,
readback and writes; shader warmup/order effects prevent attributing the small
case's improvement to compression. Compression and decompression execute on the
main thread. At 128³, compressed load/upload peaked at 32.63 ms before viewport
rendering; use raw storage when playback responsiveness matters more than disk use.
The callback budget is soft and cannot interrupt an in-progress compression call.

## Validation and reproduction

**136 standalone tests and 59 Blender checks passed** for this release:
20 GPU/compression checks, 20 compressed animated-bake checks, 7 compressed
timer/scrub/cancel checks and 12 background save/load checks. New standalone cases
cover exact bytes, raw fallback, legacy compatibility, cancellation, failed writes,
corrupt-stream bounds, invalid decoded fields and operation without NumPy.

After loading the add-on with `scripts/dev_load.py` in a disposable Blender scene,
run `scripts/compression_validate.py` for GPU checks and the table above. For
compressed animation checks, import `scripts.animation_validate` and call
`run_suite(compressed=True)`, then separately import `scripts.animation_ui_validate`
and call `run(compressed=True)`. Wait for the asynchronous UI report before
running another test. `scripts/source_save_validate.py` runs in background Blender.
Reports are in [validation/compression027](validation/compression027).

Viewport cache storage remains distinct from solver checkpoints. Compression
adds no wavelet upres, sparse bricks, physics resume, asynchronous streaming or
render-engine output.
