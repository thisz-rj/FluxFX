# FluxFX 0.42.0 package test

Tested the supplied ZIP in Blender 5.3.0 Alpha (b2e052b7172a) on Apple M5 Pro, Metal, October 7, 2026.

Result: PASS for all seven targeted checks.

- Add-on registration: all 30 classes registered.
- GPU diagnostics: Metal compute and image load/store available; all 105 texels in the writable 3D texture probe matched exactly.
- Packaged native Metal module: 65,536 elements, two dispatches, zero mismatches.
- Dense smoke: 12 steps at 32³ through Blender operators; changing, finite, nonnegative density; pressure projection reduced divergence.
- VDB export and volume creation: exported one simulated frame, created the material and volume, and loaded density, heat and temperature grids after dependency-graph evaluation.
- Native sparse/dense comparison: 32³, three steps; zero reported density, velocity and pressure differences.
- Unregistration: scene property removed; original installed add-on registered again and original scene restored.

Package SHA-256: `5714c6aa8d62f8ab910d020486a36783a93bb3c93091d16b9f60ee5e8a8a7292`.
The installed add-on's non-bytecode package files also matched the supplied ZIP byte for byte. Testing used an extracted copy under a separate module name and a temporary scene. No source changes or preference saves were made.

Scope: this is a targeted compatibility and smoke test, not a full regression suite, long simulation stability run, final render validation, or realtime performance benchmark. Smoke timing includes synchronous completion but excludes viewport rendering. Mesh collisions, combustion and long cache sequences were not exercised.

Test-harness corrections: export channel IDs must be uppercase; Blender's sequence grids require dependency-graph evaluation before inspection. These were test setup issues, not package defects. A separate graphical process could not launch from the command environment, so the completed tests ran in the existing graphical Blender session using a temporary scene.

See report.json for measured values and the retained VDB sample under cache/vdb.

---

Archived from the tester's RESULTS.md. The referenced `report.json` and VDB
sample were not supplied with it. The package hash equals a deterministic
`scripts/package.py` build of `claude-development` at `b6e0102`. Not covered
here and still open: combustion and Cycles/EEVEE renders on Metal, NaN/Inf
injection, idle-cache behaviour, and the 128³ exit-criteria run. See
[RELEASE_0.42.md](../../RELEASE_0.42.md) for the in-session commands that
cover them.
