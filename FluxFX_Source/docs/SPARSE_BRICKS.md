# P1.2 — Native sparse brick pool (0.31.0)

P1.2 implements fixed-capacity 8³ and 16³ brick storage, active/free slot lists,
coordinate-to-slot lookup, six face neighbors, and active-only Metal dispatch.
The visible smoke simulation remains the dense reference. Sparse source regions,
velocity halos, visual brick overlays and density advection are later milestones.

## Blender and Python

Install `fluxfx-0.31.0.zip` in Apple Silicon Blender 5.3. Restart Blender after
replacing a loaded native module. The tested machine is Apple M5 Pro with
Blender 5.3 Alpha `b2e052b7172a`, Python 3.13.13. Source builds use
`python3 scripts/build_native.py`; see [native setup](NATIVE_CORE.md).

Choose **Native core · P1.2 → Test Sparse Brick Pool**. The test creates an arena
for each brick size in sequence, checks a 32³ voxel region, writes
`FluxFX Native Bricks.json`, and releases both pools before returning. The
native arena setting limits each pool's GPU backing buffer. It does not include
a separately retained P1.1 arena or Blender's dense simulation resources.

```python
from fluxfx.native import BrickPool
with BrickPool(side=8, capacity=4096, budget_bytes=16*2**20) as pool:
    pool.activate_box(0, 0, 0, 14, 14, 14)  # coordinates/extents in bricks
    slot = pool.lookup(0, 0, 0)
    faces = pool.neighbors(0, 0, 0)  # -X, +X, -Y, +Y, -Z, +Z
    print(pool.stats(), pool.probe(repeats=8))
    pool.deactivate(0, 0, 0)
```

Coordinates are signed integer brick coordinates in [-1048576, 1048575]. Missing
lookup/neighbors return -1. Activation is idempotent; removing an absent brick
returns false. A slot remains stable until deactivation, then may be reused for
another coordinate. Slots are diagnostic IDs, not persistent handles. Issue
commands by coordinate. A box preflights all capacity requirements before any
mutation. Exhaustion rejects activation without evicting existing bricks.

## Layout and ownership

The native CPU topology uses a fixed open-addressed hash table, slot coordinates,
an active list, reverse active positions, and a free stack. Every topology array
is reserved at construction. Deletion swap-removes from the active list and
leaves hash tombstones. Hash lookups are bounded by table size; heavy churn can
increase probe lengths. This prototype does not yet rebuild tombstone-heavy
hash tables or move topology construction to the GPU.

One P1.1 Metal arena holds the complete fixed-capacity field, active slot IDs and
six neighbor IDs per slot. Required bytes, before 256-byte rounding, are:

```
capacity × (4 × side³ + 4 + 6 × 4)
```

The field is one 32-bit value per voxel (uint32 diagnostics now, scalar storage
layout for the next stages). Free slots still consume reserved pool memory;
deactivation does not shrink the backing buffer. Capacity is limited to 262,144
bricks and must also fit the arena's 1 GiB maximum. Stats distinguish reserved
field capacity, active voxels, GPU topology, resident arena and CPU topology
array storage. CPU byte accounting excludes allocator/object overhead and
Metal/driver allocations. Close releases GPU resources; CPU topology arrays
remain until the Python capsule is destroyed.

Neighbor IDs are rebuilt in native C++ before the diagnostic dispatch and copied
to shared Metal memory. The shader reads active IDs and six neighbor IDs, then
writes a deterministic integer pattern into each active brick. Native CPU code
verifies every slot, including sentinels in inactive bricks. There is no Python
voxel loop. GPU times measure only completed command buffers; topology rebuild,
CPU preparation and verification are reported separately.

`probe()` is destructive diagnostic work: it resets the entire reserved field
to sentinels and overwrites active voxels. It is not an advection step and must
not be used to preserve simulation state. Topology changes alone do not clear
new slots or preserve meaningful field values for reuse. This stage verifies
neighbor IDs, not cross-brick interpolation, ghost cells or MAC face ownership.
Calls are synchronous and hold the GIL. The diagnostic's CPU verification uses
a temporary live-slot mask; persistent pool/topology storage does not grow.

## 8³ versus 16³ on M5 Pro

The benchmark uses a conceptual 256³ domain with a 112³ occupied voxel box:
8.374% true occupancy. It reserves the same 8 MiB field capacity for each size,
plus GPU metadata: 4,096 slots for 8³ versus 512 for 16³. GPU resident memory is
8.109 MiB versus 8.014 MiB; CPU topology arrays use 320 KiB versus 40 KiB.

A second case shifts the occupied box by eight voxels on all axes. This is still
112³ occupied voxels, but 16³ bricks must cover a 128³ region. No halo is included.

| Case | Brick side | Active bricks | Allocated-brick occupancy | Median GPU command ms | Median CPU neighbor rebuild ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Aligned | 8 | 2,744 | 8.374% | 0.0936 | 0.1094 |
| Aligned | 16 | 343 | 8.374% | 0.0627 | 0.0217 |
| Shifted | 8 | 2,744 | 8.374% | 0.0393 | 0.1494 |
| Shifted | 16 | 512 | 12.500% | 0.0452 | 0.0269 |

Each case has one warmup, then three batches of eight completed commands.
CPU preparation of the full reserved field took about 0.08–0.10 ms and full
verification about 2.2–2.4 ms per batch; these costs are excluded from GPU time.
Measurements vary with device load and clock state: an earlier aligned run
measured roughly 0.040 ms for both sizes. These short diagnostics cannot establish
a fluid speedup or a definitive winning brick size.

The concrete tradeoff is that 16³ has fewer topology entries, while the shifted
case allocates 49.3% more voxels than 8³. Keep 8³ as the baseline and retain 16³
for future advection comparisons. No dense solver benchmark, transport accuracy,
pressure correctness or realtime frame-rate claim is made by this test.

## Validation

- 54 graphical native checks passed: both sizes, empty pools, all six neighbors,
  negative/boundary coordinates, removal/reuse, inactive sentinels, capacity
  rejection, box atomicity, invalid/closed operations and cleanup.
- The actual Blender operator passed for both sizes and returned owned GPU bytes
  to baseline. Full add-on registration/save-load/unregistration passed (14 checks).
- P1.1 resource regression: 29 checks passed. P1.0 probe: 21 checks passed.
- 146 standalone Python tests passed.
- 20,000 randomized C++ topology operations passed with address and undefined
  behavior sanitizers, checked against an independent map including all neighbors.

Run `scripts/bricks_validate.py` and `scripts/bricks_ui_validate.py` in a graphical
Blender process. Raw results and native source/binary hashes are in
`validation/native_p12/`. The CPU topology test is `native/bricks_test.cpp`.
The next stage is P1.3: source-driven activation, predicted-motion halos,
delayed deactivation, compact active lists and a visible brick overlay.
