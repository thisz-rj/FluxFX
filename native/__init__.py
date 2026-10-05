"""Optional native core. Importing FluxFX does not allocate Metal resources."""


def run_probe(count=1048576, repeats=4, seed=17):
    try:
        from . import fluxfx_core
    except ImportError as exc:
        raise RuntimeError('Native core unavailable. Build it with scripts/build_native.py on Apple Silicon, or install the macOS arm64 native package.') from exc
    return fluxfx_core.run_probe(count=count,repeats=repeats,seed=seed)


class Context:
    """Command-only owner of a synchronous native Metal arena."""
    def __init__(self, budget_bytes=64*2**20):
        from . import fluxfx_core
        self._core=fluxfx_core
        self._handle=fluxfx_core.create_context(budget_bytes)

    def allocate(self, size): return self._core.allocate(self._handle,size)
    def release(self, allocation): self._core.release(self._handle,allocation)
    def dispatch(self, allocation, count, repeats=1, seed=17):
        return self._core.dispatch(self._handle,allocation,count,repeats,seed)
    def verify(self, allocation, count, seed=17):
        return self._core.verify(self._handle,allocation,count,seed)
    def stats(self): return self._core.context_stats(self._handle)
    def close(self): self._core.close_context(self._handle)
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class BrickPool:
    """Fixed-capacity native topology and GPU field. Coordinates are brick units.

    Slot IDs may be reused after deactivation; issue commands by coordinate.
    Face order is -X, +X, -Y, +Y, -Z, +Z; missing neighbors are -1.
    """
    def __init__(self, side=8, capacity=4096, budget_bytes=64*2**20):
        from . import fluxfx_core
        self._core=fluxfx_core
        self._handle=fluxfx_core.brick_create(side,capacity,budget_bytes)

    def update_regions(self, sources, grid=32, dt=1/24, linger=3, halo=1):
        self._core.brick_regions(self._handle,sources,grid,dt,linger,halo)
    def snapshot(self): return self._core.brick_snapshot(self._handle)
    def activate(self, x, y, z): return self._core.brick_command(self._handle,"activate",x,y,z)
    def deactivate(self, x, y, z): return self._core.brick_command(self._handle,"deactivate",x,y,z)
    def lookup(self, x, y, z): return self._core.brick_command(self._handle,"lookup",x,y,z)
    def neighbors(self, x, y, z): return self._core.brick_command(self._handle,"neighbors",x,y,z)
    def activate_box(self, x, y, z, nx, ny, nz):
        return self._core.brick_box(self._handle,x,y,z,nx,ny,nz)
    def stats(self): return self._core.brick_stats(self._handle)
    def probe(self, repeats=4): return self._core.brick_probe(self._handle,repeats)
    def close(self): self._core.brick_close(self._handle)
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def compare_transport(resolution=128, side=8, steps=8, displacement=(.6,.2,.1), budget_bytes=256*2**20):
    """Native scalar benchmark; displacement is voxels per step, output float32 bytes."""
    from . import fluxfx_core
    return fluxfx_core.transport_compare(resolution,side,steps,*displacement,budget_bytes)


def compare_mac(resolution=64, side=8, steps=3, mode=0, budget_bytes=256*2**20):
    """Native MAC diagnostic: localized affine=0, full affine=1, constant=2, signed box=3."""
    from . import fluxfx_core
    return fluxfx_core.mac_compare(resolution,side,steps,mode,budget_bytes)


def compare_projection(resolution=64, side=8, iterations=128, mode=1, budget_bytes=256*2**20):
    """Fixed-region unit-cell impulse projection; explicit diagnostic readback."""
    from . import fluxfx_core
    return fluxfx_core.projection_compare(resolution, side, iterations, mode, budget_bytes)


def compare_multigrid(resolution=64, side=8, cycles=4, mode=1, budget_bytes=256*2**20):
    """Fixed-region sparse/dense geometric V-cycles, with diagnostic readback."""
    if type(cycles) is not int or not 1 <= cycles <= 16:
        raise ValueError("Use 1..16 multigrid cycles")
    from . import fluxfx_core
    return fluxfx_core.projection_compare(resolution, side, 0, mode, budget_bytes, cycles)


def compare_coupled(resolution=64, side=8, steps=3, cycles=4, mode=1, schedule=1,
                    dense_full=False, budget_bytes=256*2**20):
    """Coupled transport/projection diagnostic; optional unrestricted dense reference."""
    if type(steps) is not int or not 1 <= steps <= 16:
        raise ValueError("Use 1..16 coupled steps")
    if type(cycles) is not int or not 1 <= cycles <= 16:
        raise ValueError("Use 1..16 multigrid cycles")
    if type(dense_full) is not bool:
        raise ValueError("dense_full must be bool")
    from . import fluxfx_core
    return fluxfx_core.projection_compare(resolution,side,0,mode,budget_bytes,cycles,steps,schedule,int(dense_full))


def compare_global_coupled(resolution=64, side=8, steps=3, cycles=4, mode=1,
                           schedule=1, budget_bytes=256*2**20):
    """Conservative global-support fallback versus unrestricted native dense.

    Preserves the requested initial seed, but allocates pressure AND evolving
    velocity/density support throughout the domain. This sacrifices sparsity.
    """
    if type(steps) is not int or not 1 <= steps <= 16:
        raise ValueError("Use 1..16 coupled steps")
    if type(cycles) is not int or not 1 <= cycles <= 16:
        raise ValueError("Use 1..16 multigrid cycles")
    from . import fluxfx_core
    return fluxfx_core.projection_compare(resolution,side,0,mode,budget_bytes,cycles,steps,schedule,1,1)


def compare_hybrid_coupled(resolution=64, side=8, steps=3, cycles=4, mode=1,
                           schedule=1, budget_bytes=256*2**20):
    """Fixed sparse density diagnostic with global dense pressure and velocity.

    Missing density bricks read as zero. Only validated finite trajectories are
    supported; this is not adaptive or a production simulation entry point.
    """
    if type(steps) is not int or not 1 <= steps <= 16:
        raise ValueError("Use 1..16 coupled steps")
    if type(cycles) is not int or not 1 <= cycles <= 16:
        raise ValueError("Use 1..16 multigrid cycles")
    from . import fluxfx_core
    return fluxfx_core.projection_compare(resolution,side,0,mode,budget_bytes,cycles,steps,schedule,1,1,1)


def compare_adaptive_coupled(resolution=64, side=8, steps=8, cycles=4, mode=1,
                             schedule=1, budget_bytes=256*2**20):
    """Grow-only density support with conservative full-domain GPU preflight."""
    if type(steps) is not int or not 1 <= steps <= 16:
        raise ValueError("Use 1..16 coupled steps")
    if type(cycles) is not int or not 1 <= cycles <= 16:
        raise ValueError("Use 1..16 multigrid cycles")
    from . import fluxfx_core
    return fluxfx_core.projection_compare(resolution,side,0,mode,budget_bytes,cycles,steps,schedule,1,1,1,1)


def compare_capacity_coupled(resolution=64, side=8, steps=8, cycles=4, mode=1,
                             schedule=1, budget_bytes=256*2**20):
    """Adaptive density in separate buffers, doubling capacity only when needed."""
    if type(steps) is not int or not 1 <= steps <= 16:
        raise ValueError("Use 1..16 coupled steps")
    if type(cycles) is not int or not 1 <= cycles <= 16:
        raise ValueError("Use 1..16 multigrid cycles")
    from . import fluxfx_core
    return fluxfx_core.projection_compare(resolution,side,0,mode,budget_bytes,cycles,steps,schedule,1,1,1,1,1)
