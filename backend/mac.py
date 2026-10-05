"""P0.3 staggered velocity transport; pressure projection is deliberately deferred."""
from .dense import DenseAdvection, SEED_CONSTANTS
from ..physics.config import validate_dt

FACE_OFFSETS = ((0.0, 0.5, 0.5), (0.5, 0.0, 0.5), (0.5, 0.5, 0.0))
AXIS_MASKS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
VELOCITY_NAMES = ("velocityU", "velocityV", "velocityW")
FACE_CONSTANTS = (("VEC3", "domainExtent"), ("VEC3", "cellCount"),
                  ("VEC3", "faceOffset"), ("VEC3", "axisMask"))


class DenseMACAdvection(DenseAdvection):
    def __init__(self, grid=None, settings=None, device=None):
        self._velocity = self._velocity_back = None
        self._velocity_seed = self._velocity_advect = self._density_mac = None
        super().__init__(grid, settings, device)
        self._velocity_seed = self.device.kernel("mac_seed.glsl", FACE_CONSTANTS + (
            ("VEC3", "baseVelocity"), ("FLOAT", "angularSpeed")))
        self._velocity_advect = self.device.kernel("mac_advect_velocity.glsl", FACE_CONSTANTS + (
            ("FLOAT", "dt"),), samplers=VELOCITY_NAMES, includes=("mac_sample.glsl",))
        self._density_mac = self.device.kernel("mac_advect_density.glsl", SEED_CONSTANTS + (
            ("VEC3", "cellCount"), ("FLOAT", "dt"), ("FLOAT", "sourceRate"),
            ("FLOAT", "dissipation")), sample_input=True,
            samplers=VELOCITY_NAMES, includes=("mac_sample.glsl",))
        self._velocity = [self.device.texture(shape) for shape in self.grid.face_shapes]
        self._velocity_back = [self.device.texture(shape) for shape in self.grid.face_shapes]
        self.reset()

    @property
    def allocated_bytes(self):
        return self.grid.mac_bytes

    def _face_uniforms(self, axis):
        return {"domainExtent": self.grid.extent, "cellCount": self.grid.shape,
                "faceOffset": FACE_OFFSETS[axis], "axisMask": AXIS_MASKS[axis]}

    def reset(self, seed=True):
        super().reset(seed)
        if self._velocity is None:
            return
        for axis, shape in enumerate(self.grid.face_shapes):
            uniforms = self._face_uniforms(axis) | {"baseVelocity": self.settings.velocity,
                                                   "angularSpeed": self.settings.angular_speed}
            self.device.dispatch(self._velocity_seed, self._velocity[axis], shape, uniforms)
            self._velocity_back[axis].clear(format="FLOAT", value=(0.0,))

    def upload_velocity(self, components):
        """Signed face-centered data for numerical tests/debugging only."""
        if len(components) != 3:
            raise ValueError("MAC velocity requires U, V, W components")
        # Allocate before replacing so invalid data cannot partially modify state.
        fields = [self.device.texture(shape, values, nonnegative=False)
                  for shape, values in zip(self.grid.face_shapes, components)]
        self._velocity = fields

    def read_velocity(self):
        return tuple(self.device.read(field, shape)
                     for field, shape in zip(self._velocity, self.grid.face_shapes))

    def step(self, dt=1.0 / 30.0):
        validate_dt(dt)
        sources = dict(zip(VELOCITY_NAMES, self._velocity))
        # All components gather from the SAME old velocity state before any swap.
        for axis, shape in enumerate(self.grid.face_shapes):
            self.device.dispatch(self._velocity_advect, self._velocity_back[axis], shape,
                                 self._face_uniforms(axis) | {"dt": dt}, sources=sources)
        new_sources = dict(zip(VELOCITY_NAMES, self._velocity_back))
        uniforms = self._source_uniforms() | {"cellCount": self.grid.shape, "dt": dt,
            "sourceRate": self.settings.source_rate, "dissipation": self.settings.dissipation}
        self.device.dispatch(self._density_mac, self._back, self.grid.shape, uniforms,
                             self._front, sources=new_sources)
        # Commit the complete step only after all four dispatches succeed.
        self._velocity, self._velocity_back = self._velocity_back, self._velocity
        self._front, self._back = self._back, self._front
        self.time += dt
        self.steps += 1

    def close(self):
        self._velocity = self._velocity_back = None
        self._velocity_seed = self._velocity_advect = self._density_mac = None
        super().close()
