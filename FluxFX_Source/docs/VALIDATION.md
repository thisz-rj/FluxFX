# Validation record — 2026-09-20

## Environment

| Item | Observed value |
| --- | --- |
| Blender | 5.3.0 Alpha |
| Build | b2e052b7172a, built 2026-09-20 |
| Host | arm64, macOS 27.0 |
| Backend / device type | METAL / APPLE |
| GPU vendor / renderer strings | Apple M5 Pro / Metal API |
| Compute / image load-store | true / true |
| Workgroup size limits, per axis | 1024 / 1024 / 1024 |
| Workgroup count limits, per axis | 65535 / 65535 / 65535 |

GPU validation ran inside the installed Blender window through its Python Console.
Launching a second graphical process from the automation sandbox failed before
the test script ran, so the existing application provided the real GPU context.
No `.blend` file was saved or replaced. The developer add-on remains loaded in
that session with a paused 64³ preview.

## Results

- **16 standalone tests passed**: stationary identity, exact integer/half-cell
  translation, border zero extension, exponential decay, source rate, interior
  constant preservation, physical-domain rotation, positivity, parameter
  rejection, workgroup rounding/memory sizes, missing/unsupported capabilities,
  background mode, and failed-probe behavior.
- **3D probe passed**: all 105 texels in a 7×5×3 R32F image matched the expected
  XYZ pattern exactly. This exercises all three axes and dispatch padding.
- **GPU/CPU advection comparisons passed**, with no CPU readback between steps:

| Case | Steps | Maximum absolute error |
| --- | ---: | ---: |
| Zero velocity, no source/decay | 2 | 3.103e-7 |
| Translation and open boundaries | 4 | 7.938e-7 |
| Rotation, source, decay | 8 | 2.099e-6 |
| Decay only | 3 | 4.183e-7 |

Tolerance was 2e-5. The CPU reference uses Python floating-point arithmetic;
the GPU uses R32F. Every compared result was finite and nonnegative.

- **64³ and 128³** each completed 30 steps, changed from the initial field,
  remained finite/nonnegative, reproduced the initial field exactly after seeded
  reset, and became all-zero after an empty reset. Density allocations were
  2 MiB and 16 MiB respectively. This is a correctness/stability smoke test,
  not a long-duration performance benchmark.
- Registration/unregistration passed twice in a graphical session and twice in
  a separate background process. Background diagnostics returned `BLOCKED` /
  `NOT_RUN` as designed.
- **Nine UI/lifecycle checks passed**: timer advances simulation; preview shader
  compiles; no runtime errors; pause removes timer; release clears resources;
  undo callback clears resources; file-load callback clears resources; disabling
  during playback clears resources; re-registration restores a paused preview.
  The undo and file-load cleanup functions were invoked directly; no user file
  loading or undo history was exercised by this automated test.
- Visual inspection confirmed the sidebar, live XZ density texture, 64³ controls,
  paused 60-step state, and correct scaling on the current Retina display.
- Blender's extension validator accepted the manifest and packaged extension.

Raw evidence: [GPU validation JSON](validation/m5-pro-gpu.json) and
[UI/lifecycle JSON](validation/m5-pro-ui.json). Reproduce with the commands in
the repository README and the supplied validation scripts.

## Not established by these tests

No GPU timing/FPS claim, full smoke dynamics, pressure divergence reduction,
mass conservation, walls/collisions, scene timeline playback, baked render
integration, full volume raymarching, long-run memory profiling, or alternate
hardware/backend support. Those require the later milestones and their own
acceptance tests.
