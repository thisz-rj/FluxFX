"""Optional scalar correction and bounded vorticity confinement GPU passes."""
from math import prod
from .mac import VELOCITY_NAMES,AXIS_MASKS,FACE_CONSTANTS,FACE_OFFSETS

class DetailPasses:
    def __init__(self,grid,device):
        self.grid=grid;self.device=device
        self.predictor=self.reverse=self.transport_kernel=None
        self.curl=self.curl_kernel=self.force_kernel=None
        self.face_predictor=self.face_kernel=None

    @property
    def allocated_bytes(self):
        return prod(self.grid.shape)*((8 if self.predictor is not None else 0)+(16 if self.curl is not None else 0))+ (4*sum(prod(s) for s in self.grid.face_shapes) if self.face_predictor is not None else 0)

    def transport(self,field,velocities,dt):
        if self.predictor is None:
            self.predictor=self.device.texture(self.grid.shape);self.reverse=self.device.texture(self.grid.shape)
            self.transport_kernel=self.device.kernel('transport_scalar.glsl',(
                ('VEC3','domainExtent'),('VEC3','cellCount'),('FLOAT','dt')),sample_input=True,
                samplers=VELOCITY_NAMES,includes=('mac_sample.glsl','closed_sample.glsl'))
        common={'domainExtent':self.grid.extent,'cellCount':self.grid.shape}
        self.device.dispatch(self.transport_kernel,self.predictor,self.grid.shape,common|{'dt':dt},field,sources=velocities)
        self.device.dispatch(self.transport_kernel,self.reverse,self.grid.shape,common|{'dt':-dt},self.predictor,sources=velocities)
        return {'predictorField':self.predictor,'reverseField':self.reverse}

    def transport_velocity(self,fields,dt):
        """Predict each signed face component; reverse sampling is fused with correction."""
        if self.face_predictor is None:
            self.face_predictor=[self.device.texture(s) for s in self.grid.face_shapes]
            self.face_kernel=self.device.kernel('transport_face.glsl',FACE_CONSTANTS+(("FLOAT","dt"),),
                sample_input=True,samplers=VELOCITY_NAMES,includes=('mac_sample.glsl',))
        sources=dict(zip(VELOCITY_NAMES,fields))
        for axis,shape in enumerate(self.grid.face_shapes):
            common={'domainExtent':self.grid.extent,'cellCount':self.grid.shape,
                    'faceOffset':FACE_OFFSETS[axis],'axisMask':AXIS_MASKS[axis]}
            self.device.dispatch(self.face_kernel,self.face_predictor[axis],shape,common|{'dt':dt},fields[axis],sources=sources)

    def confine(self,fields,outputs,dt,strength,limit):
        if self.curl is None:
            self.curl=self.device.texture(self.grid.shape,channels=4)
            self.curl_kernel=self.device.kernel('curl.glsl',(('VEC3','invCell'),),samplers=VELOCITY_NAMES,output_format='RGBA32F')
            self.force_kernel=self.device.kernel('confinement.glsl',(('VEC3','invCell'),('VEC3','axisMask'),
                ('FLOAT','dt'),('FLOAT','curlStrength'),('FLOAT','forceLimit')),sample_input=True,samplers=('curlField',))
        common={'invCell':tuple(1/h for h in self.grid.cell_size)}
        self.device.dispatch(self.curl_kernel,self.curl,self.grid.shape,common,sources=dict(zip(VELOCITY_NAMES,fields)))
        for axis,shape in enumerate(self.grid.face_shapes):
            self.device.dispatch(self.force_kernel,outputs[axis],shape,common|{'axisMask':AXIS_MASKS[axis],
                'dt':dt,'curlStrength':strength,'forceLimit':limit},fields[axis],sources={'curlField':self.curl})

    def close(self):
        self.predictor=self.reverse=self.transport_kernel=None
        self.curl=self.curl_kernel=self.force_kernel=None
        self.face_predictor=self.face_kernel=None
