"""P0.5 closed-box thermal smoke with pressure-corrected MAC velocities."""
from .thermal import DenseThermalAdvection
from .pressure import PressureProjector
from .mac import VELOCITY_NAMES, FACE_CONSTANTS
from ..physics.emission import Emission, pack_sources, SOURCE_TABLE_SHAPE
from .dense import SEED_CONSTANTS
from .detail import DetailPasses
from ..physics.pressure import PressureSettings
from ..physics.config import validate_dt
from ..physics.interaction import validate_live_update


class DenseProjectedSmoke(DenseThermalAdvection):
    def __init__(self, grid=None, settings=None, device=None, projector_class=None, *, colliders=()):
        self.combustion = None
        self.solids = None
        if colliders:
            from ..physics.config import GridSpec
            from .collision import SolidDevice, SolidPressureProjector
            grid = grid or GridSpec()
            from .moving_collision import MovingSolidDevice
            moving=(settings or PressureSettings()).moving_colliders
            if moving and any(c.shape=='MESH' for c in colliders):
                raise ValueError('Mesh colliders are static; disable Moving colliders and Reset')
            device = self.solids = (MovingSolidDevice if moving else SolidDevice)(grid, colliders, device)
            from .solid_multigrid import SolidMultigridProjector
            from .multigrid import use_multigrid
            projector_class = (SolidMultigridProjector if not moving and use_multigrid(grid,settings or PressureSettings())
                               else SolidPressureProjector)
        self.projector = None
        self.detail = None
        self.turbulence = None
        self.faulted = False
        self._source_table = self._source_data = None
        self._multi_scalar = self._multi_velocity = None
        super().__init__(grid, settings or PressureSettings(), device)
        if projector_class is None:
            from .multigrid import MultigridPressureProjector, use_multigrid
            projector_class = MultigridPressureProjector if use_multigrid(self.grid, self.settings) else PressureProjector
        self.projector = projector_class(self.grid, self.settings, self.device)
        self.detail = DetailPasses(self.grid,self.device)
        from .turbulence import TurbulencePasses
        self.turbulence=TurbulencePasses(self.grid,self.device)
        if self.settings.combustion_enabled:
            from .combustion import CombustionPasses
            self.combustion=CombustionPasses(self.grid,self.device)
        self._closed_scalar = self.device.kernel("closed_advect_scalar.glsl", SEED_CONSTANTS + (
            ("VEC3", "cellCount"), ("FLOAT", "dt"), ("FLOAT", "sourceRate"),
            ("FLOAT", "dissipation"), ("VEC3", "sourceStart"), ("FLOAT", "correctedTransport"), ("FLOAT", "sourceProfile"), ("FLOAT", "targetDensity")), sample_input=True,
            samplers=VELOCITY_NAMES+("predictorField","reverseField"), includes=("mac_sample.glsl", "emission_weight.glsl", "closed_sample.glsl", "correct_scalar.glsl"))
        self._emitting_velocity = self.device.kernel("emitting_advect_velocity.glsl", FACE_CONSTANTS + (
            ("FLOAT", "dt"), ("VEC3", "sourceCenter"), ("VEC3", "sourceStart"),
            ("FLOAT", "sourceRadius"), ("FLOAT", "sourceProfile"), ("VEC3", "emissionVelocity"), ("FLOAT", "emissionCoupling"), ("FLOAT", "correctedVelocity")),
            samplers=VELOCITY_NAMES+("originalFaceField","facePredictor"), includes=("mac_sample.glsl", "emission_weight.glsl","correct_velocity_fused.glsl"))
        self.reset()

    @property
    def allocated_bytes(self):
        return self.turbulence.allocated_bytes + (self.combustion.allocated_bytes if self.combustion else 0) + super().allocated_bytes + (self.solids.allocated_bytes if self.solids else 0) + self.projector.allocated_bytes + (512 if self._source_table is not None else 0) + self.detail.allocated_bytes

    def reset(self, seed=True):
        super().reset(seed)
        self.faulted = False
        if self.combustion:self.combustion.reset()
        if self.solids is not None:
            self.solids.clear_solid(self._front,self._back)
            self._front,self._back=self._back,self._front
            if self._temperature is not None:
                self.solids.clear_solid(self._temperature,self._temperature_back)
                self._temperature,self._temperature_back=self._temperature_back,self._temperature
        if self.projector is not None:
            self.projector.reset()
            self.projector.enforce_walls(self._velocity, self._velocity_back)
            self._velocity, self._velocity_back = self._velocity_back, self._velocity

    def upload_velocity(self, components):
        super().upload_velocity(components)
        if self.solids is not None:
            self.projector.enforce_walls(self._velocity,self._velocity_back)
            self._velocity,self._velocity_back=self._velocity_back,self._velocity
        self.projector.reset()

    def upload(self, values):
        super().upload(values)
        if self.solids is not None:
            self.solids.clear_solid(self._front,self._back)
            self._front,self._back=self._back,self._front
        self.projector.reset()

    def upload_temperature(self, values):
        super().upload_temperature(values)
        if self.solids is not None:
            self.solids.clear_solid(self._temperature,self._temperature_back)
            self._temperature,self._temperature_back=self._temperature_back,self._temperature
        self.projector.reset()

    def update_settings(self, settings):
        """Apply live parameters between steps, preserving all fields and pressure."""
        validate_live_update(self.settings, settings)
        self.settings = settings
        self.projector.settings = settings

    def move_colliders(self, colliders, dt):
        """Update boundaries before a substep. Runtime bounds rigid surface motion."""
        if not self.settings.moving_colliders or self.solids is None:
            raise ValueError('Enable Moving colliders and Reset first')
        validate_dt(dt)
        if self.faulted:raise RuntimeError('Reset required after a failed GPU step')
        try:
            self.solids.update(colliders,dt)
            self.solids.remap(self)
            self.projector.ready=False
        except Exception:
            self.faulted=True
            raise

    def measure_projection(self):
        return self.projector.metrics() | {"step": self.steps, "simulation_time": self.time}

    def step(self, dt=1.0 / 30.0, emission=None, sources=None):
        validate_dt(dt)
        if sources is not None:
            self._prepare_sources(sources)
        if self.faulted:
            raise RuntimeError("Reset required after a failed GPU step")
        try:
            self._step(dt, emission or Emission(self.settings.source_center), sources)
        except Exception:
            self.faulted = True
            self.projector.ready = False
            raise

    def _prepare_sources(self, sources):
        data=pack_sources(sources)
        if self._multi_velocity is None:
            self._multi_velocity=self.device.kernel("multi_advect_velocity.glsl", FACE_CONSTANTS+(
                ("FLOAT","dt"),("FLOAT","sourceCount"),("FLOAT","correctedVelocity")), samplers=VELOCITY_NAMES+("sourceTable","originalFaceField","facePredictor"),
                includes=("mac_sample.glsl","source_table.glsl","correct_velocity_fused.glsl"))
            self._multi_scalar=self.device.kernel("multi_advect_scalar.glsl", (
                ("VEC3","domainExtent"),("VEC3","cellCount"),("FLOAT","dt"),
                ("FLOAT","sourceCount"),("FLOAT","scalarChannel"),("FLOAT","dissipation"),("FLOAT","correctedTransport")),
                sample_input=True,samplers=VELOCITY_NAMES+("sourceTable","predictorField","reverseField"),
                includes=("mac_sample.glsl","source_table.glsl","closed_sample.glsl","correct_scalar.glsl"))
        if data!=self._source_data:
            table=self.device.texture(SOURCE_TABLE_SHAPE,data,nonnegative=False)
            self._source_table=table
            self._source_data=data

    def _step(self, dt, emission, emitters=None):
        old_velocity = dict(zip(VELOCITY_NAMES, self._velocity))
        velocity_detail=self.settings.velocity_advection=="MACCORMACK"
        if velocity_detail:self.detail.transport_velocity(self._velocity,dt)
        multi=emitters is not None
        if multi:old_velocity["sourceTable"]=self._source_table
        for axis, shape in enumerate(self.grid.face_shapes):
            source_uniforms=({"sourceCount":float(len(emitters))} if multi else {
                "sourceCenter":self.settings.source_center,"sourceStart":emission.start,
                "sourceRadius":self.settings.source_radius,"sourceProfile":float(self.settings.source_profile=="SOLID"),"emissionVelocity":emission.velocity,
                "emissionCoupling":emission.coupling})
            self.device.dispatch(self._multi_velocity if multi else self._emitting_velocity,
                self._velocity_back[axis],shape,self._face_uniforms(axis)|{"dt":dt,"correctedVelocity":float(velocity_detail)}|source_uniforms,
                sources=old_velocity|{"originalFaceField":self._velocity[axis],
                    "facePredictor":self.detail.face_predictor[axis] if velocity_detail else self._velocity[axis]})
        self.device.dispatch(self._buoyancy, self._buoyancy_scratch, self.grid.face_shapes[2],
            {"dt": dt, "thermalLift": self.settings.thermal_lift,
             "densityWeight": self.settings.density_weight}, self._velocity_back[2],
            sources={"densityField": self._front, "temperatureField": self._temperature})
        provisional = [self._velocity_back[0], self._velocity_back[1], self._buoyancy_scratch]
        if self.settings.turbulence_strength>0:
            provisional=self.turbulence.apply(self,provisional,dt)
        # Old velocity has been fully consumed; reuse its storage for corrected fields.
        if self.settings.vorticity_strength>0:
            self.detail.confine(provisional,self._velocity,dt,self.settings.vorticity_strength,self.settings.vorticity_limit)
            self.projector.project(self._velocity,self._velocity_back,dt)
            self._velocity,self._velocity_back=self._velocity_back,self._velocity
        else:
            self.projector.project(provisional, self._velocity, dt)
        sources = dict(zip(VELOCITY_NAMES, self._velocity))
        if multi:
            sources["sourceTable"]=self._source_table
            common={"domainExtent":self.grid.extent,"cellCount":self.grid.shape,"dt":dt,
                    "sourceCount":float(len(emitters))}
        else:
            common=self._source_uniforms()|{"cellCount":self.grid.shape,"dt":dt,"sourceStart":emission.start,"sourceProfile":float(self.settings.source_profile=="SOLID")}
        channels = [
                (0.,self._front,self._back,self.settings.source_rate,self.settings.dissipation),
                (1.,self._temperature,self._temperature_back,self.settings.heat_source_rate,self.settings.cooling)]
        if self.combustion:channels.append((2.,self.combustion.fuel,self.combustion.spare,self.settings.fuel_source_rate,0.))
        for channel,front,back,rate,decay in channels:
            corrected=self.settings.scalar_advection=="MACCORMACK"
            transport_sources=(self.detail.transport(front,dict(zip(VELOCITY_NAMES,self._velocity)),dt)
                               if corrected else {'predictorField':front,'reverseField':front})
            source_uniforms=({"scalarChannel":channel} if multi else {"sourceRate":rate,"targetDensity":rate if channel==0 and self.settings.density_mode=="TARGET" else -1.})|{"correctedTransport":float(corrected)}
            self.device.dispatch(self._multi_scalar if multi else self._closed_scalar,back,self.grid.shape,
                common|source_uniforms|{"dissipation":decay},front,sources=sources|transport_sources)
        self._front, self._back = self._back, self._front
        self._temperature, self._temperature_back = self._temperature_back, self._temperature
        if self.combustion:
            self.combustion.fuel,self.combustion.spare=self.combustion.spare,self.combustion.fuel
            self.combustion.react(self,dt)
        self.time += dt
        self.steps += 1

    def preview_field(self,channel):
        if channel=='COLLISION':
            if self.solids is None:raise ValueError('Add a collider and Reset for collision display')
            return self.solids.mask
        if channel in {'FUEL','FLAME'}:
            if not self.combustion:raise ValueError('Enable combustion and Reset for fuel/flame display')
            return self.combustion.fuel if channel=='FUEL' else self.combustion.flame
        return self.temperature if channel=='TEMPERATURE' else self.density

    def close(self):
        if self.turbulence:self.turbulence.close()
        if self.combustion:self.combustion.close()
        if self.projector is not None:
            self.projector.close()
        self.projector = None
        if self.detail is not None:self.detail.close()
        self.detail = None
        self.turbulence = None
        self._closed_scalar = None
        self._emitting_velocity = None
        self._multi_scalar = self._multi_velocity = None
        self._source_table = self._source_data = None
        super().close()
        if self.solids is not None:self.solids.close()
        self.combustion = None
        self.solids = None
