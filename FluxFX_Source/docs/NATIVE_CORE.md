# P1.0 — Native Metal core skeleton

This milestone is packaged as **FluxFX 0.29.0 for macOS arm64**. It adds a compiled
`fluxfx_core.abi3.so` extension using C++17, Objective-C++ and Metal. Python sends
count/repeat/seed commands and receives a small report. Native code allocates,
compiles, submits, waits, checks every result and destroys its resources. The
kernel is a deterministic uint32 operation, not fluid physics. The dense smoke
engine remains the 0.28 implementation and numerical reference.

## Use and build

Install `fluxfx-0.29.0.zip` in Blender 5.3's Install from Disk menu. The binary is
included. Expand **Native core · P1.0** and click **Test Native Metal Core**.
Read `FluxFX Native Core.json` in Blender's Text Editor for timing/device details.
The diagnostic does not reset the existing dense preview or allocate persistent
GPU state. Importing FluxFX does not load the binary until the diagnostic is used.
A missing/unsupported native binary produces an actionable error report.

For source builds, unpack the source ZIP, open its repository directory and run:

```sh
python3 scripts/build_native.py
python3 scripts/package.py --out-dir ..
```

This build requires a local Apple Silicon Mac, Xcode with the macOS SDK and Python
development headers. The installed Blender's reported Python include directory
was absent. The build instead uses Xcode's Python 3.9 headers with
`Py_LIMITED_API=0x03090000`; an explicit `--python-include PATH` overrides discovery.
It links system Foundation/Metal and libc++, resolving Python symbols from the
host, without linking another Python interpreter. Deployment target is macOS 13.
No pybind11, third-party package download or CMake installation is required.
The compiler treats warnings as errors. Generated binaries are excluded from Git
and the source ZIP; build the source ZIP before packaging an installable extension.

The extension loaded successfully into Blender's Python **3.13.13**. This is the
tested host; the ABI target is not a claim that all Python versions, architectures
or Blender builds have been tested. Windows, Linux, Intel Macs, native texture
interop and a standalone fluid runtime are outside P1.0.

## Command and ownership contract

```python
from fluxfx.native import fluxfx_core
report = fluxfx_core.run_probe(count=1048576, repeats=4, seed=17)
assert report['status'] == 'PASS'
assert fluxfx_core.resource_status()['owned_buffer_bytes'] == 0
```

Count is 1–16,777,216 uint32 elements (at most 64 MiB); repeats is 1–32; seed is
0–4,294,967,295. Oversized/negative/noninteger requests fail before GPU allocation.
Each dispatch writes `(index ^ seed) * 1664525 + 1013904223`, modulo 2³²; the seed
increments each dispatch. Dispatch rounds up workgroups and guards bounds. The
CPU checks all elements of the final dispatch, including uint32 seed wraparound.

Each call owns a Metal device reference, queue, compiled library/function,
pipeline and shared output buffer. ARC scopes/autorelease pools release these
references after completed execution, including C++ exception unwinding. Buffer
ownership has an explicit counter checked by validation. Zero owned bytes means
no buffer retained by the core; it is not a measurement of driver caches, Blender
allocations or total process/GPU memory. P1.1 will introduce persistent ownership,
arenas and a general hard budget. P1.0's fixed probe-size cap is not that system.

The call is synchronous and holds Python's GIL. It can briefly block Blender,
especially on first shader compilation. It does not install callbacks, threads,
handlers or native pointers in scene data. The binary stays loaded by Python,
but GPU objects are scoped to calls. Restart Blender before testing a rebuilt
binary; Python module reload does not reliably unload a native dynamic library.

## Timing and validation

`gpu_command_ms` uses Metal `GPUStartTime`/`GPUEndTime` after
`waitUntilCompleted`. These are completed command-buffer execution intervals,
not host submission timings or per-instruction timestamps. A missing timestamp
is returned as null, never relabeled as zero-duration GPU work. `setup_ms`,
`submit_wait_ms` and `verify_ms` separately report host work. Setup includes
compilation/allocation; submit/wait includes host scheduling and all repeats.

On 2026-10-02, Apple M5 Pro, Blender 5.3.0 Alpha build `b2e052b7172a`:

- 21 native checks passed across counts 1, 7, 257, 4,097, 1,048,576 and 16,777,216.
- Every tested element matched, including non-workgroup-aligned counts and seed wraparound.
- Completed GPU timestamps were returned for all 18 size-sweep dispatches.
- 32 further create/run/destroy cycles passed with zero retained owned buffer bytes.
- The actual Blender operator returned FINISHED and wrote a PASS report.
- 146 standalone dense/reference tests and 13 Blender save/load checks passed.

The 64 MiB probe's three command intervals were approximately 0.378, 0.435 and
1.101 ms; CPU verification took 8.78 ms. First setup took about 78 ms, while later
calls benefited from system shader caches. These are diagnostic samples, not a
fluid benchmark or a throughput guarantee. Background Blender in the execution
environment imported the extension but returned `No Metal device available`;
graphical Blender successfully ran the tests. Headless Metal availability is not
assumed.

Run `scripts/native_validate.py` in graphical Blender with the source repository
available. Reports and binary/source build metadata are in
[validation/native_p10](validation/native_p10).

## API references

Apple documents checking GPU start/end timestamps after command completion:
[MTLCommandBuffer GPUStartTime](https://developer.apple.com/documentation/metal/mtlcommandbuffer/gpustarttime).
The binding follows Python's documented
[Limited C API and Stable ABI](https://docs.python.org/3.11/c-api/stable.html).
