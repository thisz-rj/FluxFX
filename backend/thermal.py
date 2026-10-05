"""P0.4 GPU temperature transport and explicit vertical buoyancy."""
from math import prod
from .mac import DenseMACAdvection, VELOCITY_NAMES
from .dense import SEED_CONSTANTS
from ..physics.thermal import ThermalSettings
from ..physics.config import validate_dt


class DenseThermalAdvection(DenseMACAdvection):
    def __init__(self, grid=None, settings=None, device=None):
        self._temperature = self._temperature_back = self._buoyancy_scratch = None
        self._temperature_seed = self._buoyancy = None
        super().__init__(grid, settings or ThermalSettings(), device)
        self._temperature_seed = self.device.kernel("temperature_seed.glsl", SEED_CONSTANTS + (
            ("FLOAT", "seedTemperature"),))
        self._buoyancy = self.device.kernel("buoyancy.glsl", (
            ("FLOAT", "dt"), ("FLOAT", "thermalLift"), ("FLOAT", "densityWeight")),
            sample_input=True, samplers=("densityField", "temperatureField"))
        self._temperature = self.device.texture(self.grid.shape)
        self._temperature_back = self.device.texture(self.grid.shape)
        self._buoyancy_scratch = self.device.texture(self.grid.face_shapes[2])
        self.reset()

    @property
    def temperature(self):
        return self._temperature

    @property
    def allocated_bytes(self):
        return self.grid.mac_bytes + 8 * prod(self.grid.shape) + 4 * prod(self.grid.face_shapes[2])

    def reset(self, seed=True):
        super().reset(seed)
        if self._temperature is None:
            return
        for texture in (self._temperature, self._temperature_back, self._buoyancy_scratch):
            texture.clear(format="FLOAT", value=(0.0,))
        if seed:
            self.device.dispatch(self._temperature_seed, self._temperature, self.grid.shape,
                self._source_uniforms() | {"seedTemperature": self.settings.initial_temperature})

    def upload_temperature(self, values):
        self._temperature = self.device.texture(self.grid.shape, values, nonnegative=False)

    def read_temperature(self):
        return self.device.read(self._temperature, self.grid.shape)

    def step(self, dt=1.0 / 30.0):
        validate_dt(dt)
        old_velocity = dict(zip(VELOCITY_NAMES, self._velocity))
        for axis, shape in enumerate(self.grid.face_shapes):
            self.device.dispatch(self._velocity_advect, self._velocity_back[axis], shape,
                                 self._face_uniforms(axis) | {"dt": dt}, sources=old_velocity)
        # Previous scalar state drives acceleration. Newly injected heat acts next step.
        self.device.dispatch(self._buoyancy, self._buoyancy_scratch, self.grid.face_shapes[2],
            {"dt": dt, "thermalLift": self.settings.thermal_lift,
             "densityWeight": self.settings.density_weight}, self._velocity_back[2],
            sources={"densityField": self._front, "temperatureField": self._temperature})
        next_velocity = [self._velocity_back[0], self._velocity_back[1], self._buoyancy_scratch]
        sources = dict(zip(VELOCITY_NAMES, next_velocity))
        common = self._source_uniforms() | {"cellCount": self.grid.shape, "dt": dt}
        self.device.dispatch(self._density_mac, self._back, self.grid.shape,
            common | {"sourceRate": self.settings.source_rate, "dissipation": self.settings.dissipation},
            self._front, sources=sources)
        # The scalar kernel is also valid for signed temperature excess.
        self.device.dispatch(self._density_mac, self._temperature_back, self.grid.shape,
            common | {"sourceRate": self.settings.heat_source_rate, "dissipation": self.settings.cooling},
            self._temperature, sources=sources)
        spare_w = self._velocity_back[2]
        self._velocity_back, self._velocity = self._velocity, next_velocity
        self._buoyancy_scratch = spare_w
        self._front, self._back = self._back, self._front
        self._temperature, self._temperature_back = self._temperature_back, self._temperature
        self.time += dt
        self.steps += 1

    def close(self):
        self._temperature = self._temperature_back = self._buoyancy_scratch = None
        self._temperature_seed = self._buoyancy = None
        super().close()
