# 0.42 render export: OpenVDB → Blender Volume → Cycles / EEVEE

A baked FluxFX cache now renders as smoke and fire in Cycles and EEVEE.
Each baked frame is written as one OpenVDB file. A Blender **Volume** object
plays that sequence, and its **Principled Volume** material shades smoke from
`density` and fire as blackbody emission. Fire colour is evaluated by Blender's
own blackbody function in the shader; no RGB colour is baked into the files.
The viewport preview (the FluxFX overlay) is unchanged and still plays the
FluxFX cache.

## Workflow

The **Render volume · Cycles / EEVEE** panel section holds these controls,
separate from the developer diagnostics.

1. Set up and bake as before (**Cache → Bake**). With **Write VDB for
   rendering** on (the default), the bake writes `<bake folder>/vdb/` alongside
   the cache. The fields captured for the cache feed the VDB writer, so there is
   no second GPU readback.
2. With **Update render volume** on (the default), the bake's final tick creates
   or updates the `FluxFX Render Volume` object. You can also run
   **Create / Update Render Volume** manually.
3. To export a cache baked without VDB (or by 0.41), choose it as the playback
   folder and click **Export VDB from Cache**. The export runs as a timer job
   (cancellable) and writes the same files.
4. Render (F12) in Cycles or EEVEE. The material controls apply immediately
   while a render volume exists. **Rebuild / Apply Material** recreates
   FluxFX's nodes if they were deleted.

If Blender's Python has no `openvdb` module, the bake still writes the cache and
reports that VDB output was skipped. Blender 5.2 and 5.3 bundle OpenVDB 13;
FluxFX finds it even when Blender runs as a Python module.

## Files

```
<bake folder>/vdb/
  export.json          manifest: format, shape, start/end, fps, grids, per-frame stats, status
  fluxfx_00001.vdb     first baked frame
  fluxfx_00002.vdb
  ...
```

Files are numbered from 1, whatever the first baked frame is. The Volume uses
`frame_start = first baked frame` and `frame_offset = 0`, so scene frame
`start + k` shows file `k + 1`; this also works for negative frame numbers.
The Volume uses `sequence_mode = CLIP`, so it shows nothing outside the baked
range. Each file is written to `name.partial` and renamed into place. The
manifest is republished atomically after every frame, so an interrupted or
failed export keeps a valid prefix (status `CANCELLED` or `FAILED`).

| Grid | Source | Units | Background |
| --- | --- | --- | --- |
| `density` | DENSITY | FluxFX density | 0 |
| `heat` | TEMPERATURE | K above ambient (signed, as simulated) | 0 |
| `temperature` | TEMPERATURE + ambient | absolute K, clamped at 0 | ambient |
| `flame` | FLAME | fuel burned per second (combustion rate) | 0 |
| `fuel` | FUEL | unburned fuel | 0 |

- All grids are float32 FogVolumes, written with tolerance 0. Exported values
  equal the cached fields exactly (`temperature` = `heat` + ambient).
- Voxels equal to the background stay inactive, which keeps files sparse. A
  32³ fire takes about 1.3 MiB per 16 frames, against 8 MiB of cache.
- The grid transform places voxel centres inside the domain's `[-0.5, 0.5]³`
  box. The Volume object is parented to the domain with identity transforms,
  so it follows the domain exactly like the preview does.
- Ambient temperature (**Ambient temperature (K)**, default 293.15 K) is applied
  at export time only.

## Material

`FluxFX Smoke and Fire` is built from named nodes. Settings changes update
only those nodes; edits made elsewhere in the tree are kept.

- **Smoke:** Principled Volume `Density Attribute = density`, multiplied by
  **Smoke density** (default 5, the same as Blender's Quick Smoke), with
  **Smoke color**.
- **Fire amount:** `f = clamp(source / reference)`. The source is `flame` in
  Flame mode and `heat` in Temperature mode. The reference is **Full flame at**,
  or by default the highest value in the export. The Blackbody Intensity input
  is driven by `f × Fire intensity`, so emission fades to zero wherever nothing
  burns.
- **Flame mode** (default): the temperature is linked from `f`, rising from
  `0.5 × Flame temperature` at the weakest-burning edges (deep red) to
  **Flame temperature** in the core (orange-yellow). The fastest-burning
  regions are both the hottest and the brightest.
- **Temperature mode:** the colour comes from the exported absolute
  `temperature` grid (Temperature Attribute = `temperature`, multiplier 1).
  The emission is gated by `heat`. Ungated, ambient air at 293 K glows faintly
  red across the whole domain box, because Cycles uses a constant deep-red
  blackbody colour below 800 K; the headless validation renders and detects
  that case. This mode is physically literal: the Basic Fire preset peaks
  near 900 K, which is only a dull red glow. Use it with a hotter simulation,
  or raise the intensity.
- **Smoke only:** no emission.

### Why the defaults are 2000 K and intensity 20

Cycles and EEVEE emit `σ·T⁴` per unit length, with `σ ≈ 1.8·10⁻¹⁴`. Blender's
unit scale makes this dim next to typical lighting: at 1800 K that is 0.19 per
metre. The default 1 m domain produces flames about 0.2 m thick, so a fire at
intensity 1 adds about 0.04 to the image, which is invisible under a sun of
strength 2–5. Calibration renders of the Basic Fire preset under AgX and
Standard view transforms selected:

- **2000 K core:** orange with a yellow core under AgX, not white.
- **Intensity 20:** a clearly visible flame that does not clip.

Emission scales with flame thickness, so larger domains need less intensity
and smaller domains need more. Temperature changes the colour; intensity
changes only the brightness.

## EEVEE

EEVEE renders the same Volume and material. Its volumetrics are evaluated on
a froxel grid (Render Properties → Volumes → Resolution), so small or thin
flames look soft at the default tile size. Use 1:2 or 1:1 tiles for close-ups.
The headless validation renders EEVEE through Mesa's software OpenGL and checks
for visible blackbody fire. Metal EEVEE still needs validation on the Mac.

## Performance

VDB writing reuses the cache's captured fields, so it adds no GPU readback. Its
cost is one transposition copy per grid (FluxFX's x-fast layout to OpenVDB's
`[x][y][z]` array), `copyFromArray` and OpenVDB's own compressed write.

These figures come from Blender 5.2.2 bpy on llvmpipe in the Linux sandbox, so
they are relative, not M5 Pro timings. For the 32³ Basic Fire over 16 frames,
the VDB files total 1.3 MiB against 8.0 MiB of cache. Exporting 10 cached
frames takes 0.1 s.

## Validation

- **Unit:** `tests/test_volume_export.py` covers grid plan, absolute
  temperature, file numbering, sequence mapping, transform, x/y/z orientation,
  exact values, manifest, atomic failure and ordering. It runs without
  Blender or OpenVDB.
- **Headless Blender:** `scripts/headless_validate.py` (Blender 5.2.2 bpy,
  OpenVDB 13, llvmpipe; runs in CI) checks:
  - a fire bake writes 16 VDB frames whose every grid equals the cache exactly;
  - scene frames 1/9/16/17 map to files 1/9/16/none;
  - all five grids load in the evaluated Volume;
  - export from an existing compressed cache matches;
  - the Cycles renders show:
    - visible fire in Flame mode;
    - a red glow in Temperature mode, with no ambient glow;
    - no emission in Smoke only;
    - smoke visibly different from an empty render;
  - EEVEE renders visible fire.

## Limitations

- **No motion blur:** there is no velocity grid. The playback cache does not
  store velocity, so Volume motion blur is unavailable.
- **Main thread:** export and VDB writing run on Blender's main thread, as the
  cache writer does.
- **Resolution:** the dense grid resolution is the render resolution. There is
  no upres.
- **Re-export:** a re-export into the same bake folder replaces its files. The
  Volume's grids are unloaded so stale data is never shown.
- **Volume precision:** Blender's Volume defaults to Half render precision
  (Volume data → Render → Precision). That is sufficient for these value
  ranges; use Full for exact values.
- **Viewport display:** the Volume object also displays in the viewport.
  Disable it in the viewport (monitor icon) if it doubles up with the FluxFX
  preview; renders are unaffected.
