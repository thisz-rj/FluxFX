"""GPU weighted-Jacobi projection with stationary free-slip box walls."""
from math import prod, ceil
from .device import BlenderGPUDevice
from .mac import VELOCITY_NAMES
from ..physics.config import validate_dt
from ..physics.pressure import PressureSettings, divergence_stats


class PressureProjector:
    def __init__(self, grid, settings=None, device=None):
        self.grid = grid
        self.settings = settings or PressureSettings()
        self.device = device or BlenderGPUDevice()
        self.inv_cell = tuple(1 / h for h in grid.cell_size)
        self.wall = self.device.kernel("pressure_walls.glsl", (("FLOAT", "componentAxis"),), sample_input=True)
        self.divergence = self.device.kernel("pressure_divergence.glsl", (("VEC3", "invCell"),), samplers=VELOCITY_NAMES)
        self.jacobi = self.device.kernel("pressure_jacobi.glsl", (
            ("VEC3", "invCell"), ("FLOAT", "dt"), ("FLOAT", "relaxation")),
            sample_input=True, samplers=("divergenceField",))
        self.gradient = self.device.kernel("pressure_gradient.glsl", (
            ("VEC3", "invCell"), ("FLOAT", "dt"), ("FLOAT", "componentAxis")),
            sample_input=True, samplers=("pressureField",))
        self.scale = self.device.kernel("pressure_scale.glsl", (("FLOAT","factor"),), sample_input=True)
        self.bounded = [self.device.texture(s) for s in grid.face_shapes]
        self.pressure = self.device.texture(grid.shape)
        self.spare = self.device.texture(grid.shape)
        self.before = self.device.texture(grid.shape)
        self.after = self.device.texture(grid.shape)
        self.ready = False
        self.last_dt = None
        self.last_iterations = 0

    @property
    def uses_impulse(self):
        return (self.settings.pressure_warm_start == "IMPULSE" or
                (self.settings.pressure_warm_start == "AUTO" and len(getattr(self,"levels",())) > 1))

    @property
    def allocated_bytes(self):
        return 4 * (4 * prod(self.grid.shape) + sum(prod(s) for s in self.grid.face_shapes))

    def reset(self):
        self.ready = False
        self.last_dt = None
        self.last_iterations = 0
        for texture in (self.pressure, self.spare, self.before, self.after, *self.bounded):
            texture.clear(format="FLOAT", value=(0.0,))

    def enforce_walls(self, fields, outputs):
        for axis, shape in enumerate(self.grid.face_shapes):
            self.device.dispatch(self.wall, outputs[axis], shape, {"componentAxis": float(axis)}, fields[axis])

    def compute_divergence(self, fields, target):
        self.device.dispatch(self.divergence, target, self.grid.shape,
            {"invCell": self.inv_cell}, sources=dict(zip(VELOCITY_NAMES, fields)))

    def project(self, fields, outputs, dt):
        validate_dt(dt)
        self.ready = False
        previous_dt, self.last_dt = self.last_dt, None
        self.enforce_walls(fields, self.bounded)
        self.compute_divergence(self.bounded, self.before)
        # Solve for impulse q=dt*p: Laplacian(q)=div(u), u_new=u-grad(q).
        # Its units do not change when adaptive dt changes. LEGACY retains 0.16.
        impulse = self.uses_impulse
        solve_dt = 1.0 if impulse else dt
        previous_solve_dt = (1.0 if previous_dt is not None else None) if impulse else previous_dt
        if impulse and previous_dt is not None and abs(dt/previous_dt-1.0)>1e-6:
            # The incremental pressure force is proportional to physical dt.
            # Scale its guess before short remainder steps; otherwise residual
            # from a longer step can dominate an almost divergence-free input.
            self.device.dispatch(self.scale,self.spare,self.grid.shape,
                                 {"factor":dt/previous_dt},self.pressure)
            self.pressure,self.spare=self.spare,self.pressure
        self.solve_pressure(solve_dt, previous_solve_dt)
        # The original inputs are no longer sampled after wall conditioning.
        for axis, shape in enumerate(self.grid.face_shapes):
            self.device.dispatch(self.gradient, outputs[axis], shape,
                {"invCell": self.inv_cell, "dt": solve_dt, "componentAxis": float(axis)},
                self.bounded[axis], sources={"pressureField": self.pressure})
        self.compute_divergence(outputs, self.after)
        self.last_dt = dt
        self.ready = True

    def solve_pressure(self, dt, previous_dt):
        # Impulse mode passes dt=1 here, preserving the guess across physical dt changes.
        if previous_dt != dt:
            self.pressure.clear(format="FLOAT", value=(0.0,))
        # Jacobi smooths across cells: scale work with resolution squared.
        scaled = ceil(self.settings.pressure_iterations * max(1.0, (max(self.grid.shape) / 64) ** 2))
        multiplier = self.settings.pressure_cold_multiplier if previous_dt != dt else 1
        self.last_iterations = min(4096, scaled * multiplier)
        uniforms = {"invCell": self.inv_cell, "dt": dt,
                    "relaxation": self.settings.pressure_relaxation}
        for _ in range(self.last_iterations):
            self.device.dispatch(self.jacobi, self.spare, self.grid.shape, uniforms,
                                 self.pressure, sources={"divergenceField": self.before})
            self.pressure, self.spare = self.spare, self.pressure

    def metrics(self):
        """Explicit synchronous readback; never invoked by normal playback."""
        if not self.ready:
            raise RuntimeError("Take a simulation step before measuring projection")
        before = self.device.read(self.before, self.grid.shape)
        after = self.device.read(self.after, self.grid.shape)
        return divergence_stats(before, after) | {
            "solver": "JACOBI",
            "pressure_storage": "IMPULSE" if self.uses_impulse else "LEGACY",
            "iterations": self.last_iterations,
            "base_iterations_at_64": self.settings.pressure_iterations,
            "relaxation": self.settings.pressure_relaxation,
            "boundary": "closed_free_slip", "units": "1/s",
            "before_stage": "after_wall_conditioning"}

    def close(self):
        self.ready = False
        self.last_dt = None
        self.bounded = None
        self.pressure = self.spare = self.before = self.after = None
        self.wall = self.divergence = self.jacobi = self.gradient = self.scale = None
