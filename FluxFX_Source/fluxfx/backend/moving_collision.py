"""GPU-only mask refresh and rigid wall velocities for interactive colliders."""
from math import prod
from .collision import SolidDevice
from ..physics.collider_motion import validate_motion, velocity_rows


class MovingSolidDevice(SolidDevice):
    def __init__(self,grid,colliders,device=None):
        validate_motion(colliders,colliders)
        self.wall_kernels=[]
        super().__init__(grid,colliders,device)
        self.colliders=tuple(colliders)
        self.previous_mask=self.mask
        self.work_a=self.base.texture(grid.shape)
        self.work_b=self.base.texture(grid.shape)
        self.wall_fields=[self.base.texture(shape) for shape in grid.face_shapes]
        self.wall_table=self.base.texture((4,24,1))
        self.mask_kernel=self.base.kernel('moving_mask.glsl',(('VEC3','domainExtent'),('VEC4','row0'),
            ('VEC4','row1'),('VEC4','row2'),('FLOAT','shapeKind'),('FLOAT','owner')),sample_input=True)
        self.velocity_kernel=self.base.kernel('moving_wall.glsl',(('VEC3','domainExtent'),('FLOAT','componentAxis')),
            samplers=('solidField','wallTable'))
        self.remap_scalar=self.base.kernel('moving_remap_scalar.glsl',sample_input=True,samplers=('solidField','oldSolidField'))
        self.remap_face=self.base.kernel('moving_remap_face.glsl',(('FLOAT','componentAxis'),),sample_input=True,
            samplers=('solidField','oldSolidField','boundaryField'))

    def kernel(self,filename,constants=(),sample_input=False,samplers=(),includes=(),output_format='R32F'):
        wall=filename in ('pressure_walls.glsl','pressure_gradient.glsl')
        if wall:
            samplers=(*samplers,'boundaryField')
            includes=('moving_boundary.glsl',*includes)
        if filename=='pressure_divergence.glsl':
            shader=self.base.kernel(filename,constants,sample_input,(*samplers,'solidField'),('solid_boundary.glsl',*includes),output_format)
            self.decorated.append(shader)
        else:shader=super().kernel(filename,constants,sample_input,samplers,includes,output_format)
        if wall:self.wall_kernels.append(shader)
        return shader

    def dispatch(self,shader,output,shape,uniforms=None,input_field=None,sources=None):
        if any(shader is item for item in self.wall_kernels):
            sources=dict(sources or {},boundaryField=self.wall_fields[int(uniforms['componentAxis'])])
        super().dispatch(shader,output,shape,uniforms,input_field,sources)

    @property
    def allocated_bytes(self):
        return 12*prod(self.grid.shape)+4*sum(prod(s) for s in self.grid.face_shapes)+384

    def update(self,colliders,dt):
        validate_motion(self.colliders,colliders)
        self.previous_mask=self.mask
        front,back=self.work_a,self.work_b
        front.clear(format='FLOAT',value=(0.,))
        table=[0.]*96
        for index,(old,new) in enumerate(zip(self.colliders,colliders)):
            uniforms={'domainExtent':self.grid.extent,'shapeKind':float(new.shape=='BOX'),'owner':float(index+1)}
            uniforms.update({f'row{i}':row for i,row in enumerate(new.inverse_rows)})
            self.base.dispatch(self.mask_kernel,back,self.grid.shape,uniforms,front)
            front,back=back,front
            table[index*12:index*12+12]=[v for row in velocity_rows(old,new,dt) for v in row]
        self.mask,self.work_a,self.work_b=front,self.previous_mask,back
        self.wall_table=self.base.texture((4,24,1),table,nonnegative=False)
        for axis,shape in enumerate(self.grid.face_shapes):
            self.base.dispatch(self.velocity_kernel,self.wall_fields[axis],shape,
                {'domainExtent':self.grid.extent,'componentAxis':float(axis)},
                sources={'solidField':self.mask,'wallTable':self.wall_table})
        self.colliders=tuple(colliders)

    def remap(self,solver):
        sources={'solidField':self.mask,'oldSolidField':self.previous_mask}
        for front,back in ((solver._front,solver._back),(solver._temperature,solver._temperature_back)):
            self.base.dispatch(self.remap_scalar,back,self.grid.shape,input_field=front,sources=sources)
        solver._front,solver._back=solver._back,solver._front
        solver._temperature,solver._temperature_back=solver._temperature_back,solver._temperature
        for axis,shape in enumerate(self.grid.face_shapes):
            self.base.dispatch(self.remap_face,solver._velocity_back[axis],shape,{'componentAxis':float(axis)},
                solver._velocity[axis],sources=sources|{'boundaryField':self.wall_fields[axis]})
        solver._velocity,solver._velocity_back=solver._velocity_back,solver._velocity
        if solver.combustion:
            c=solver.combustion
            self.base.dispatch(self.remap_scalar,c.spare,self.grid.shape,input_field=c.fuel,sources=sources)
            c.fuel,c.spare=c.spare,c.fuel
            c.flame.clear(format='FLOAT',value=(0.,))

    def close(self):
        self.work_a=self.work_b=self.previous_mask=self.wall_table=None
        self.wall_fields=[];self.wall_kernels=[];self.colliders=()
        self.mask_kernel=self.velocity_kernel=self.remap_scalar=self.remap_face=None
        super().close()
