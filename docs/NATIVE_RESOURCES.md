# P1.1 — Native GPU resource layer (0.30.0)

P1.1 adds persistent Metal resources to the P1.0 compiled core. It does not
change the dense smoke solver or implement sparse physics. The next stage is
P1.2: an 8³ brick pool, coordinate lookup, neighbors and a comparison with 16³.

## Setup and use

Use Blender 5.3 on Apple Silicon and install `fluxfx-0.30.0.zip`. For a source
checkout, run `python3 scripts/build_native.py` with Xcode installed; see
[NATIVE_CORE.md](NATIVE_CORE.md) for the stable-ABI build details. Restart Blender
after replacing a loaded native binary: Python reload does not unload it.

In the FluxFX native panel, set the arena budget (default 64 MiB), then run
**Test Native Resources**. The test writes and verifies 1 MiB inside the arena,
returns its range to the pool, and retains the backing buffer for reuse. The
Text Editor report is `FluxFX Native Resources.json`. Release closes the context.
Undo, redo, file loading, add-on shutdown and scene switching also release the
UI-owned context. Scene switching is observed by a 0.25-second timer.

Python scripts can use the command-only wrapper:

```python
from fluxfx.native import Context
with Context(16 * 2**20) as ctx:
    handle = ctx.allocate(4 * 2**20)
    result = ctx.dispatch(handle, count=2**20, repeats=4, seed=17)
    print(result, ctx.stats())
    ctx.release(handle)
```

Scripts own their contexts and should close them explicitly or use `with`.
Capsule destruction also releases resources. UI lifecycle hooks own only the
UI context. Allocation handles are opaque, never reused during normal process
lifetime, and rejected after release, context close, or in another context.

## Resource contract

Each context owns one shared-storage Metal buffer, a queue and a compiled
compute pipeline. The budget is 256-byte aligned, between 256 bytes and 1 GiB;
the UI accepts whole MiB. Suballocations round up to 256 bytes and charge that
padding to the budget. A first-fit free list merges adjacent released ranges.
There can be at most 65,536 live handles. Allocation can fail from fragmentation
even when total free space is sufficient; stats expose the largest free range.
No additional backing buffers are allocated during pool operations or dispatch.
Contents are not initialized by allocate; write them before interpreting them.

The hard limit covers the context's **owned backing-buffer bytes**. It excludes
Metal driver allocations, pipelines, CPU metadata and Blender/dense-solver
resources. Multiple independently created contexts each have their own budget.
The global owned-byte counter includes all contexts and the legacy probe in the
loaded module. It is not a measurement of total process or system GPU memory.
Metal's recommended working-set size is reported as guidance, not enforced as
a global budget. A shared buffer arena is used here; private storage, Metal
heaps, texture pooling and asynchronous in-flight reclamation are deferred.

Native calls are synchronous and hold the Python GIL. Dispatch waits for GPU
completion before output verification or release, so no resource may still be
in use when the next Python command executes. The diagnostic writes a known
uint32 pattern, with a count limit of 16,777,216 and 1–32 repeats. It performs
no fluid loop in Python and is not a fluid performance benchmark.

GPU timestamps measure each completed command buffer. Missing timestamps are
returned as `None`; CPU submit/wait and verification are separate timings.
This is command-level profiling, not per-stage GPU counter sampling.

## Validation on Apple M5 Pro

Blender 5.3 Alpha `b2e052b7172a`, Python 3.13.13, Metal, 2026-10-02:

- 29 native resource checks passed: budget rejection, alignment, exhaustion,
  neighboring-range integrity, requested-size bounds, stale/foreign handles,
  coalescing, 1,000 reuse cycles with one buffer, and 32 context lifecycles.
- 9 Blender operator/lifecycle checks passed, including retained arena reuse,
  release, undo/load cleanup and the actual scene-switch timer.
- The P1.0 native regression probe passed all 21 checks.
- 146 standalone Python tests passed; 14 save/load checks passed, including
  persistence of the native budget setting.
- The portable allocator passed 10,000 randomized operations with Clang address
  and undefined-behavior sanitizers enabled.

Eight 4 MiB diagnostic dispatches in a retained 16 MiB arena measured
0.032–0.041 ms GPU command time after the first dispatch (0.090 ms).
These are individual observations with no speedup claim. Exact output checks
reported zero mismatches. Device capabilities reported a 32-thread execution
width and a 1,024-thread maximum for this pipeline.

Raw reports and source/binary hashes are in `validation/native_p11/`.
Run `scripts/resources_validate.py` and `scripts/resources_ui_validate.py` inside
a graphical Blender process. The UI test assumes this add-on is registered.
Background Blender on this machine cannot provide a Metal device; use it for
registration/save-load checks only.

References: Apple's [working-set guidance](https://developer.apple.com/documentation/metal/mtldevice/recommendedmaxworkingsetsize),
[buffer binding](https://developer.apple.com/documentation/metal/mtlcomputecommandencoder/setbuffer(_:offset:index:)),
and [Metal feature tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf).
