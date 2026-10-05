# P1.8 global coverage fallback — 0.38.0

The 0.37 unrestricted audit exposed a modeling error: truncating pressure to a
localized smoke region changes the velocity even when density is nearly empty
elsewhere. Version 0.38 separates the initial velocity seed from the solve mask.
The new fallback preserves the localized seed and emitter schedule, then gives
pressure, velocity and density full-domain support at every multigrid level.
All bricks are allocated. Existing restricted-support diagnostics remain as
negative controls; the interactive dense smoke engine is unchanged.

## Validation

Tested on Apple M5 Pro / Metal in graphical Blender 5.3.0 Alpha build
`b2e052b7172a`, Python 3.13.13. Native code was built with the local Apple Silicon
Xcode toolchain. GPU validation requires graphical Blender; background Blender
has no usable Metal device in this setup.

115 checks passed. The 32³ independent NumPy oracle covers 8³/16³ bricks,
localized/disconnected/zero velocity seeds and static/moving/intermittent
emission, with three steps and four V-cycles per step. CPU tolerance is 1e-4.
Native dense tolerance is 1e-6. The suite also checks allocation coverage, mass
agreement, walls, unused face padding, invalid inputs, budget rejection and
owned-buffer cleanup. The 64³/128³ cases run eight steps with eight V-cycles per
step and moving emission. Both brick sizes matched native dense density,
velocity, pressure and divergence with measured maximum difference zero.

Legacy truncated-support negative controls still fail: velocity differences
are 0.34635 at 64³ and 0.42381 at 128³; density differences are 0.01864 and
0.01591. This makes the coverage correction observable in the same test suite.

| Domain / brick | Allocated bricks | Brick memory MiB | Dense memory MiB | Brick GPU ms | Dense GPU ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 64³ / 8³ | 512 | 13.330 | 12.666 | 103.85 | 55.74 |
| 64³ / 16³ | 64 | 12.948 | 12.666 | 102.78 | 57.24 |
| 128³ / 8³ | 4096 | 106.643 | 100.948 | 586.51 | 285.67 |
| 128³ / 16³ | 512 | 103.581 | 100.948 | 582.61 | 285.67 |

Timings are single-run completed GPU work for all eight steps, excluding setup,
compilation and readback; they are not viewport FPS. Memory includes each
engine's owned fields and hierarchy; the comparison holds both engines, so its
peak owned buffer memory is their sum. Driver overhead is excluded. Smoke
occupancy (>1e-6 density) is about 0.93% at 64³ and 0.61% at 128³, while allocated
brick occupancy is 100%. This is not the planned 256³ / 8% occupancy benchmark.

Regression checks also passed: coupled 113, multigrid 171, projection 154,
MAC velocity 96, scalar transport 55, regions 24, resources 29, standalone
Python 146 and Blender save/load 15. The new Blender operator report and
resource cleanup passed. Raw reports and source/binary hashes are archived in
[validation/native_p18_global](validation/native_p18_global).

## Run it

Build using `python3 scripts/build_native.py` with Xcode installed, then package
with `python3 scripts/package.py`. Install `fluxfx-0.38.0.zip` in Blender 5.3
Apple Silicon using Preferences → Get Extensions → Install from Disk. Restart
Blender after replacing an already-loaded native binary.

In FluxFX choose **Native core · P1.8 → Compare Global Coverage**. The fixed
64³ diagnostic writes **FluxFX Global Coverage.json** in Blender's Text Editor.
It reports `sparse_efficiency_gate=false` even when numerical checks pass.

The Python entry point is `fluxfx.native.compare_global_coupled`, defaulting to
64³, 8³ bricks, three steps, four cycles and a moving source. The native engine
runs all fluid loops. For full validation, execute
`scripts/global_coverage_validate.py` from a graphical Blender process with the
repository on Python's import path. Its output is
`test-results/global-coverage-validation.json`.

## What remains open

This proves native brick-layout correctness for the tested full-domain cases.
It does not prove sparse efficiency, dynamic topology, persistent simulation,
256³ performance, or complete dense 0.28 physics parity. Temperature, buoyancy,
MacCormack, vorticity, turbulence, collisions and combustion are not included
in this native coupled test. No new Blender GPU API limitation was encountered;
the correction is to pressure-domain modeling, implemented in native Metal.

Next, separate density storage from the pressure/velocity support policy and
validate a hybrid global pressure approach or an adaptive support scheme against
this unrestricted baseline. Report errors and total work together. P1.8 stays
open until accuracy and sparse resource savings pass together; feature ports
remain deferred.

## Follow-up in 0.39

[Hybrid density](HYBRID_DENSITY.md) keeps pressure and velocity dense/global while
allocating a separate fixed sparse density region. It provides measured memory
savings with matching tested trajectories; adaptive support remains open.
