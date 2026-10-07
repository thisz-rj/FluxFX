# Blender GPU API findings

Version 0.11 uses the viewport projection matrix and evaluated domain transform
for perspective/orthographic rays. Premultiplied alpha composites in a POST_PIXEL
draw handler. Scene depth is not sampled, so objects do not occlude smoke.
This is viewport output only, not an EEVEE/Cycles volume; see [scene domain](SCENE_DOMAIN.md).

Version 0.10 uses the same verified R32F compute path for residual, restriction,
and prolongation. The multigrid hierarchy adds GPU texture storage but no
per-cycle CPU readback or native interop. Unsupported coarsening uses Jacobi;
see [multigrid](MULTIGRID.md).

P0.9 does not assume a GPU timestamp/finish API. A dependency compute pass and
one-float readback synchronize measured work; timings include that overhead.
Render timings similarly include a one-pixel framebuffer read. These are wall
measurements rather than pure GPU timings or viewport FPS; see [P0.9](P0_9.md).

P0.8 introduces five synchronous one-float texture reads per adaptive step after
GPU max reductions. This is a deliberate exception to the original readback-free
playback path and may stall the GPU/CPU. Fixed-step mode avoids these reads.
No async readback or native reduction API is assumed; see [P0.8](P0_8.md).

P0.7 renders directly from the R32F textures with a fragment shader and manual
trilinear sampling. A float `GPUOffScreen` framebuffer verified Metal rendering
against analytic values. The inset does not sample scene depth or integrate
with EEVEE/Cycles; see [P0.7](P0_7.md).

P0.5 adds weighted-Jacobi pressure passes through the same verified API. Many
small dispatches and fixed iteration counts limit performance/convergence; this
is not a native solver or a realtime benchmark. Explicit divergence measurement
pauses playback and reads back synchronously. See [P0.5](P0_5.md).

P0.3 uses the same verified API path, with three additional sampler inputs per
pass and signed R32F velocity fields. All are validated on the same M5 Pro build;
see [P0.3 validation](P0_3.md). P0.4 adds two signed temperature textures and a
separate W-velocity scratch texture to avoid in-place buoyancy updates; see
[P0.4 validation](P0_4.md). No new native interop API is assumed.

Observed against installed Blender **5.3.0 Alpha b2e052b7172a**, Apple M5 Pro,
Metal, 2026-09-20. Alpha APIs may change; rerun the supplied validation on a new
build. Online 5.3 API pages were not retrievable during this work; the installed
build's Python docstrings and actual GPU execution were the primary checks.

## Verified locally

1. `GPUTexture((x, y, z), format='R32F')` plus
   `GPUShaderCreateInfo.image(..., 'R32F', 'FLOAT_3D', ..., qualifiers={'WRITE'})`
   compiled and wrote the expected 3D contents through Metal. R32F is used for
   both density fields. Unsupported formats/devices produce a blocked probe;
   there is no silent CPU or 2D-atlas substitute.
2. `gpu.platform.renderer_get()` returned `Metal API`, while `vendor_get()`
   returned `Apple M5 Pro`. These are reported as received; FluxFX does not
   assume the renderer string must contain the chip name.
3. Background mode cannot validate the interactive `gpu` context. Diagnostics
   skip GPU calls and report `BLOCKED`, with `probe_3d: NOT_RUN`. This does not
   mean the machine lacks compute support.
4. `GPUTexture.read()` is synchronous CPU readback. FluxFX uses it only in
   diagnostics/tests. Buffer dimensions are flattened explicitly to validate
   x-fast scalar layout. The viewport samples the GPU texture directly.
5. The installed `GPUTexture` type does not expose a `wrap_mode` method.
   Advection implements border behavior with integer `texelFetch` and explicit
   bounds checks, including trilinear weights. It does not rely on texture
   sampler wrap defaults. The slice preview uses coordinates in `[0, 1]`.
6. `gpu.state` exposes no Python memory-barrier function in this build.
   Blender's [Python compute-dispatch implementation](https://github.com/blender/blender/blob/main/source/blender/python/gpu/gpu_py_compute.cc)
   issues texture-fetch and shader-image-access barriers after dispatch. The
   multi-step GPU tests passed with no intermediate readback. This source link
   tracks `main`; it is supporting evidence, not a pinned source audit of the
   installed binary. Revalidate when changing Blender builds.
7. Workgroup per-axis size/count queries are available. A total-invocations
   query is not exposed among the inspected capabilities; the conservative
   4×4×4 group is validated through actual compilation/dispatch. Likewise, the
   generic maximum texture size is reported but is not treated as proof that
   any particular 3D allocation or format will succeed.
8. No explicit `GPUTexture.free()` lifecycle is used. Dropping owning Python
   references releases these wrapped resources. Draw handlers and timers must
   be removed before dropping state; both are removed during teardown.

## Scope and engineering limits

- Python coordinates the passes on Blender's main thread. The prototype has
  no independent asynchronous GPU worker or native resource-sharing interface.
- No documented general-purpose Python SSBO/sparse allocator path or native
  Metal/Vulkan texture import was established here. P1 must investigate those
  integration questions explicitly instead of assuming zero-copy interop.
- `perf_counter` around dispatch measures host submission overhead, not completed
  GPU work. No GPU timestamp claim or realtime frame-rate guarantee is made.
- The R32F probe establishes a specific working path, not universal support for
  every 3D format, texture size, GPU, or backend. Windows/Linux/Vulkan are untested.
- P0.2 uses open boundaries, a fixed step, and nonconservative semi-Lagrangian
  transport. Large displacements can smear density; CFL control is deferred to
  P0.8. The simple density slice does not establish final smoke-render quality.
- Only descriptors persist in `.blend` files. The GPU fields have no cache,
  checkpoint, timeline seek, render-engine integration, or export path yet.

## Reference entry points

- [Blender GPU module and compute example](https://docs.blender.org/api/5.2/gpu.html)
- [GPU capabilities](https://docs.blender.org/api/main/gpu.capabilities.html)
- [GPU shader creation](https://docs.blender.org/api/current/gpu.shader.html)
- [Shader resource declarations in Blender source](https://github.com/blender/blender/blob/main/source/blender/python/gpu/gpu_py_shader_create_info.cc)

These references guide API usage. The recorded test JSON is the evidence for the
specific installed 5.3 build and M5 Pro hardware.

## 0.16 format validation

Writable RGBA32F 3D textures were successfully exercised on the recorded M5 Pro /
Metal build for curl storage, alongside R32F scalar fields. This does not establish
format support on other GPUs. The new passes use the same main-thread dispatch
and wrapped-reference cleanup path; no native interop or GPU timestamp API was
added. See [smoke detail](SMOKE_DETAIL.md) for performance and numerical limits.

## 0.17 compute path

The direct coarse solver uses a small R32F 3D coefficient texture (64×64×1),
keeping the existing image/sampler API. Motion correction uses three R32F face
predictors and fused reverse sampling. Both paths passed the recorded Metal
checks; other GPUs remain untested. No new GPU timestamp, asynchronous worker,
cache or render-engine API was added. See [motion detail](MOTION_DETAIL.md) for
the speed/quality tradeoffs and unchanged preview scheduling limitations.


## 0.20 static-collider hierarchy

The existing writable R32F/RGBA32F 3D texture and dispatch API supports the masked
pressure hierarchy and corrected transport. No new Blender API workaround is
needed. Reset reads the static GPU mask once, builds connected aggregates on the
CPU, and computes a small graph pseudoinverse with Blender's bundled NumPy.
Pressure cycles and transport stay on the GPU; no per-cycle pressure readback.
The reset path can pause the UI, particularly at 128³. This is a dense prototype
and has not gained native Metal interop, sparse storage, mesh voxelization, or
EEVEE/Cycles volume output. See [0.20 details](COLLIDER_DETAIL.md).

## 0.21 moving colliders

Moving primitives use the existing public compute/image API. A tiny CPU table
holds rigid wall velocity coefficients; the dense mask and face velocities are
rebuilt on the GPU. Python coordinates dispatches and allocates the 384-byte table
texture per update. No native geometry upload or mesh collision API is used.
Dynamic mode uses masked Jacobi; the NumPy-built static multigrid hierarchy is not
updated live. See [moving collider limitations and timings](MOVING_COLLIDERS.md).

## 0.22 fuel and flame

Combustion uses existing writable R32F 3D textures and separate compute passes.
The source table's previously unused final scalar now stores fuel emission rate.
A burn-rate field drives an approximate flame preview, not a Blender Volume datablock
or emission material. Checkpoints use synchronous GPU readback and bundled NumPy;
format v1 is scripting-only and excludes colliders/scene history. See
[combustion notes](COMBUSTION.md) for scope, reproducibility and performance limits.

## 0.23 static meshes

Evaluated mesh triangles are read through `to_mesh` and released with `to_mesh_clear`.
The CPU BVHTree builds a sampled signed distance only during Reset; Python does not
have a native GPU mesh-to-SDF facility in this implementation. R32F uploads feed the
existing voxel mask and multigrid path. Comparing evaluated snapshots detects edits
but adds CPU work during playback. Preview is the resolved mask, not a renderable
Blender fluid volume. See [mesh collisions](MESH_COLLISIONS.md) for supported geometry,
subgrid limitations and measured costs.

## 0.25–0.27 cache and compression

Local scalar caches now support integer-frame playback, fixed or direct-keyframe
input baking, and optional lossless zlib compression through Python's standard
library. GPU readback and texture upload use the established Blender API; all
I/O, compression and decompression run on the main thread. There is no native
GPU texture sharing, asynchronous disk worker or OpenVDB/render-engine export.
At 128³, decompression can consume a substantial part of the frame budget; see
[compression measurements](CACHE_COMPRESSION.md). Historical no-cache statements
above describe the earlier milestones. Playback files omit velocity/pressure and
cannot resume fluid physics.

## 0.28 decoded frame retention

A portable CPU LRU retains decoded frames within a configurable payload limit.
Prefetch uses a separate Blender main-thread timer, one read/decode per callback,
and pending prefetch is cancelled on a new frame request. There is no Python
worker thread touching Blender or GPU resources. I/O can still occupy the UI
thread, and continuous first-pass throughput remains limited by decoding and
upload cost. RAM-hit measurements and exact memory scope are documented in
[frame memory](FRAME_MEMORY.md).

## P1.0 native probe

Package 0.29 adds a separate compiled Objective-C++ Metal path. It establishes
shared-buffer allocation, compute dispatch, completed command-buffer timestamps
and scoped cleanup inside graphical Blender. It does not import Blender GPU
textures or replace the dense solver. See [native-core notes](NATIVE_CORE.md) for
ABI/build constraints, headless limitations and the distinction between GPU
command timing and host submission timing.

## 0.42 render export

Cycles and EEVEE output now goes through files, not GPU interop:
- Baked fields are written as OpenVDB with Blender's bundled `openvdb` Python
  module (OpenVDB 13 in Blender 5.2/5.3). When Blender runs as a Python module,
  that module is outside `sys.path`; FluxFX adds
  `bpy.utils.resource_path('LOCAL')/python/lib/python3.x/site-packages`.
- A Volume object plays the sequence (`is_sequence`, `frame_start`,
  `frame_duration`, `frame_offset`, `sequence_mode`).
- Principled Volume shades it.

Verified in Blender 5.2.2:
- the evaluated Volume's `grids.frame_filepath` follows `frame_start`. Inspect
  grids on `obj.evaluated_get(depsgraph).data` and call `grids.load()`; the
  original `obj.data` does not resolve the sequence frame;
- a new `ShaderNodeOutputMaterial` must be made active (`is_active_output`);
- the Temperature input multiplies the Temperature Attribute and is used alone
  when the attribute name is empty;
- Cycles' blackbody colour is constant below 800 K, so ambient temperatures
  glow faintly unless the emission is gated.

Python-defined property edits do not fire `depsgraph_update_post`, so render
settings reach the material through property `update` callbacks. See
[render export](RENDER_EXPORT.md).
