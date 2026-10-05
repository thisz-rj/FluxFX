"""Dense ping-pong density transport. No UI, scene, or timeline access."""
from ..physics.config import AdvectionSettings, GridSpec, validate_dt
from .device import BlenderGPUDevice

SEED_CONSTANTS = (("VEC3", "domainExtent"), ("VEC3", "sourceCenter"), ("FLOAT", "sourceRadius"))
ADVECTION_CONSTANTS = SEED_CONSTANTS + (
    ("VEC3", "baseVelocity"), ("FLOAT", "angularSpeed"), ("FLOAT", "dt"),
    ("FLOAT", "sourceRate"), ("FLOAT", "dissipation"),
)


class DenseAdvection:
    def __init__(self, grid=None, settings=None, device=None):
        self.grid = grid or GridSpec()
        self.settings = settings or AdvectionSettings()
        self.device = device or BlenderGPUDevice()
        self._seed = self.device.kernel("seed.glsl", SEED_CONSTANTS)
        self._advect = self.device.kernel("advect.glsl", ADVECTION_CONSTANTS, sample_input=True)
        self._front = self.device.texture(self.grid.shape)
        self._back = self.device.texture(self.grid.shape)
        self.time = 0.0
        self.steps = 0
        self.reset()

    @property
    def density(self):
        return self._front

    def _source_uniforms(self):
        return {"domainExtent": self.grid.extent, "sourceCenter": self.settings.source_center,
                "sourceRadius": self.settings.source_radius}

    def reset(self, seed=True):
        self._front.clear(format="FLOAT", value=(0.0,))
        self._back.clear(format="FLOAT", value=(0.0,))
        if seed:
            self.device.dispatch(self._seed, self._front, self.grid.shape, self._source_uniforms())
        self.time = 0.0
        self.steps = 0

    def upload(self, values):
        """Test/debug entry point, not part of the playback path."""
        self._front = self.device.texture(self.grid.shape, values)
        self._back.clear(format="FLOAT", value=(0.0,))
        self.time = 0.0
        self.steps = 0

    def step(self, dt=1.0 / 30.0):
        validate_dt(dt)
        uniforms = self._source_uniforms() | {
            "baseVelocity": self.settings.velocity, "angularSpeed": self.settings.angular_speed,
            "sourceRate": self.settings.source_rate, "dissipation": self.settings.dissipation,
            "dt": dt,
        }
        self.device.dispatch(self._advect, self._back, self.grid.shape, uniforms, self._front)
        self._front, self._back = self._back, self._front
        self.time += dt
        self.steps += 1

    def read_density(self):
        return self.device.read(self._front, self.grid.shape)

    def close(self):
        # GPUTexture / GPUShader own their resources; release Python references.
        self._front = self._back = self._seed = self._advect = None
