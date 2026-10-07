"""Optional bounded procedural force before pressure projection."""
from math import prod
from .mac import FACE_OFFSETS,AXIS_MASKS
from ..physics.turbulence import spectrum

class TurbulencePasses:
    def __init__(self,grid,device):
        self.grid,self.device=grid,device
        self.outputs=None;self.table=None;self.key=None;self.kernel=None
    @property
    def allocated_bytes(self):
        return 4*sum(prod(s) for s in self.grid.face_shapes)+384 if self.outputs else 0
    def apply(self,solver,fields,dt):
        s=solver.settings
        if self.outputs is None:
            self.outputs=[self.device.texture(shape) for shape in self.grid.face_shapes]
            self.kernel=self.device.kernel('turbulence.glsl',(('VEC3','domainExtent'),('VEC3','faceOffset'),('VEC3','axisMask'),
                ('FLOAT','dt'),('FLOAT','phaseTime'),('FLOAT','strength'),('FLOAT','forceLimit'),('FLOAT','maskMode'),('FLOAT','maskThreshold')),
                sample_input=True,samplers=('waveTable','densityField','temperatureField'))
        key=(s.turbulence_scale,s.turbulence_octaves,s.turbulence_seed)
        if key!=self.key:
            self.table=self.device.texture((4,2,12),spectrum(self.grid,s),nonnegative=False);self.key=key
        for axis,shape in enumerate(self.grid.face_shapes):
            self.device.dispatch(self.kernel,self.outputs[axis],shape,
                dict(domainExtent=self.grid.extent,faceOffset=FACE_OFFSETS[axis],axisMask=AXIS_MASKS[axis],dt=dt,
                     phaseTime=solver.time*s.turbulence_speed,strength=s.turbulence_strength,forceLimit=s.turbulence_limit,
                     maskMode=float(('ALL','DENSITY','HEAT').index(s.turbulence_mask)),maskThreshold=s.turbulence_threshold),fields[axis],
                sources=dict(waveTable=self.table,densityField=solver.density,temperatureField=solver.temperature))
        return self.outputs
    def close(self):self.outputs=self.table=self.kernel=self.key=None
