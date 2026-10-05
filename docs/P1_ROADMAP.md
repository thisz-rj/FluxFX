# FluxFX P1 — Native sparse smoke

The dense 0.28 reference is preserved at commit `661a9d0` and in the 0.28 source
and extension ZIPs. P1.0 ships in package 0.29.0, P1.1 in 0.30.0 and P1.2 in 0.31.0, and P1.3 in 0.32.0, and P1.4 in 0.33.0, and P1.5 in 0.34.0, and P1.6 in 0.35.0, and P1.7 in 0.36.0; P1.8 begins in 0.37.0, with a global-support fallback in 0.38.0 and hybrid density in 0.39.0 plus grow-only density in 0.40.0 and independent density capacity in 0.41.0, but remains open; package versions and research
milestone numbers are distinct. The dense solver remains available for comparison.

| Stage | Deliverable | Gate |
| --- | --- | --- |
| P1.0 | Compiled Metal core skeleton | Buffer allocation, known kernel, exact verification, completed command timing, cleanup in Blender — complete |
| P1.1 | GPU memory/resource layer | Preallocated arenas, buffer reuse, capabilities, profiling and a hard owned-buffer budget — complete |
| P1.2 | Sparse brick pool | Start 8³; active/free lists, coordinate-to-ID mapping, neighbors; benchmark 8³ versus 16³ — complete (storage/dispatch diagnostic) |
| P1.3 | Active-region system | Source activation, velocity safety halo, delayed deactivation, per-update compaction and active-brick visualization — complete for source/prediction topology; field-based retention awaits transport |
| P1.4 | Sparse scalar transport | Density advection only; compare with identical dense 128³ inputs and timestep — complete for prescribed constant velocity and fixed conservative support; also tested native 256³ |
| P1.5 | Sparse MAC velocity | U/V/W ownership, cross-brick sampling and RK2 self-advection — complete for fixed conservative topology; 96 checks pass; memory reduction but no measured speedup |
| P1.6 | Sparse divergence/pressure | Complete fixed-region Jacobi baseline: 154 checks, explicit zero-pressure truncation and closed outer walls; full-domain Blender comparison. Dynamic pressure support and full-smoke equivalence remain unproven |
| P1.7 | Sparse geometric multigrid | Complete for prescribed aligned regions: sparse levels, restriction/prolongation, V-cycles, CPU reference and common-target Jacobi benchmark; arbitrary/dynamic topology remains unproven |
| P1.8 | Dense-versus-sparse validation | IN PROGRESS: 0.41 independent density capacity passes 237 checks and avoids global-field copies during growth. Peak 128³/8³ memory falls to 85.85 MiB; full-grid support detection still prevents a net speed advantage. Local candidate support, headline benchmark and full 0.28 physics parity remain open. See DENSITY_CAPACITY.md |

The first critical comparison uses smoke occupying about 5–10% of a 128³ domain.
The headline target is a **256³-equivalent domain with about 8% smoke occupancy**.
The Blender dense reference supports at most 128³. P1.4 validates against that
shader at 128³ and compares matched native sparse/dense scalar paths at 256³;
the larger result does not include full dense smoke physics.

Report smoke occupancy separately from allocated-brick occupancy, including
partially occupied bricks, safety halos and retained inactive bricks. Measure
peak owned memory, active brick count, GPU dispatch time, topology update cost,
and total completed step time. Compare scalar error, velocity error, divergence
and total mass against the dense reference with matching discretization,
boundaries, source schedule and timesteps. Set numerical tolerances per stage
before treating a speedup as a successful result. Zero density alone is not a
sufficient reason to discard velocity or pressure support.

After the sparse reference passes those gates, port temperature, buoyancy,
MacCormack, vorticity, turbulence, collisions and combustion in that order.
Wavelet upres, advanced fire rendering and liquids remain deferred. The eventual
target is the same established physics with substantially less work in empty
space; P1.0 alone establishes no sparse-memory or fluid-performance advantage.
