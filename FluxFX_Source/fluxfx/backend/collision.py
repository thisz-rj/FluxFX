"""Static voxel mask and collision shader variants; no Blender UI dependencies."""
from math import prod
from .device import BlenderGPUDevice
from .pressure import PressureProjector

VARIANTS = {'pressure_walls.glsl', 'pressure_jacobi.glsl', 'pressure_gradient.glsl',
            'closed_advect_scalar.glsl', 'multi_advect_scalar.glsl',
            'emitting_advect_velocity.glsl', 'multi_advect_velocity.glsl', 'solid_clear.glsl',
            'transport_scalar.glsl', 'transport_face.glsl'}


class SolidDevice:
    """Delegate ordinary passes unchanged; bind a static mask on boundary variants."""
    def __init__(self, grid, colliders, device=None):
        if not 1 <= len(colliders) <= 8:
            raise ValueError('Use one to eight static colliders')
        self.base = device or BlenderGPUDevice()
        self.grid = grid
        self.decorated = []
        self.mesh_sdf = None
        self.mesh_reports = []
        self.mask = self.base.texture(grid.shape)
        spare = self.base.texture(grid.shape)
        kernel = self.base.kernel('solid_mask.glsl', (('VEC3','domainExtent'),('VEC4','row0'),
                                  ('VEC4','row1'),('VEC4','row2'),('FLOAT','shapeKind')), sample_input=True)
        mesh_values=None
        for collider in colliders:
            if collider.shape=="MESH":
                from .mesh_sdf import build_sdf
                values,report=build_sdf(grid,collider);self.mesh_reports.append(report)
                mesh_values=values if mesh_values is None else [min(a,b) for a,b in zip(mesh_values,values)]
                continue
            uniforms = {'domainExtent':grid.extent, 'shapeKind':float(collider.shape=='BOX')}
            uniforms.update({f'row{i}':row for i,row in enumerate(collider.inverse_rows)})
            self.base.dispatch(kernel,spare,grid.shape,uniforms,self.mask)
            self.mask,spare=spare,self.mask
        if mesh_values is not None:
            self.mesh_sdf=self.base.texture(grid.shape,mesh_values,nonnegative=False)
            mesh_kernel=self.base.kernel('mesh_mask.glsl',sample_input=True,samplers=('sdfField',))
            self.base.dispatch(mesh_kernel,spare,grid.shape,input_field=self.mask,sources={'sdfField':self.mesh_sdf})
            self.mask=spare
        self.clear_kernel = self.kernel('solid_clear.glsl', sample_input=True)

    def __getattr__(self, name):
        return getattr(self.base, name)

    @property
    def allocated_bytes(self):
        return (8 if self.mesh_sdf is not None else 4)*prod(self.grid.shape)

    def kernel(self, filename, constants=(), sample_input=False, samplers=(), includes=(), output_format='R32F'):
        decorated = filename in VARIANTS
        if decorated:
            samplers = (*samplers, 'solidField')
            includes = ('solid_boundary.glsl', *includes)
        kernel = self.base.kernel(filename,constants,sample_input,samplers,includes,output_format)
        if decorated: self.decorated.append(kernel)
        return kernel

    def dispatch(self, shader, output, shape, uniforms=None, input_field=None, sources=None):
        if any(shader is item for item in self.decorated):
            sources = dict(sources or {}, solidField=self.mask)
        self.base.dispatch(shader,output,shape,uniforms,input_field,sources)

    def clear_solid(self, source, target):
        self.dispatch(self.clear_kernel,target,self.grid.shape,input_field=source)

    def close(self):
        self.mask = self.clear_kernel = None
        self.decorated = []
        self.mesh_sdf = None
        self.mesh_reports = []


class SolidPressureProjector(PressureProjector):
    @property
    def uses_impulse(self):
        return True

    def solve_pressure(self, dt, previous_dt):
        # A short masked Jacobi solve cannot reliably remove a stale pressure
        # guess when the new divergence is tiny. Start at zero for stable damping.
        self.pressure.clear(format='FLOAT',value=(0.0,))
        super().solve_pressure(dt, previous_dt)

    def metrics(self):
        return super().metrics() | {'solver':'MOVING_JACOBI' if self.settings.moving_colliders else 'SOLID_JACOBI',
            'boundary':'moving_voxel_free_slip' if self.settings.moving_colliders else 'static_voxel_free_slip','warm_start':False}
