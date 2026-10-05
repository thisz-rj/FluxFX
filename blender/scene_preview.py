"""Scene-space raymarch overlay with true perspective/orthographic camera rays."""
from pathlib import Path
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from .domain import domain_object,clip_to_domain


class ScenePreview:
    def __init__(self):
        interface=gpu.types.GPUStageInterfaceInfo('fluxfx_scene_interface')
        interface.smooth('VEC2','screenPosition')
        info=gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0,'VEC2','position')
        info.vertex_out(interface)
        info.push_constant('MAT4','clipToDomain')
        info.push_constant('FLOAT','exposure')
        info.push_constant('FLOAT','thermalView')
        info.push_constant('INT','raySteps')
        info.sampler(0,'FLOAT_3D','densityField')
        info.fragment_out(0,'VEC4','fragColor')
        info.vertex_source('void main(){screenPosition=position;gl_Position=vec4(position,0.0,1.0);}')
        root=Path(__file__).resolve().parents[1]/'shaders'
        info.fragment_source(''.join((root/name).read_text() for name in ('field_sample.glsl','scene_volume.frag.glsl')))
        self.shader=gpu.shader.create_from_info(info)
        self.batch=batch_for_shader(self.shader,'TRI_FAN',{'position':((-1,-1),(1,-1),(1,1),(-1,1))})
        self.warning=''

    def render(self, texture, transform, exposure, thermal=False, samples=128):
        previous=(gpu.state.blend_get(),gpu.state.depth_test_get(),gpu.state.depth_mask_get())
        try:
            gpu.state.blend_set('ALPHA_PREMULT')
            gpu.state.depth_test_set('NONE')
            gpu.state.depth_mask_set(False)
            self.shader.bind()
            self.shader.uniform_float('clipToDomain',transform)
            self.shader.uniform_float('exposure',exposure)
            self.shader.uniform_float('thermalView',float(thermal))
            self.shader.uniform_int('raySteps',samples)
            self.shader.uniform_sampler('densityField',texture)
            self.batch.draw(self.shader)
        finally:
            gpu.state.blend_set(previous[0]);gpu.state.depth_test_set(previous[1]);gpu.state.depth_mask_set(previous[2])

    def draw(self,solver,scene):
        self.warning=''
        obj=domain_object(scene)
        if obj is None:
            self.warning='Create or select a FluxFX domain'
            return
        if not obj.visible_get(view_layer=bpy.context.view_layer):
            return
        try:
            evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            transform=clip_to_domain(bpy.context.region_data.perspective_matrix,evaluated.matrix_world)
        except ValueError:
            self.warning='Domain scale must be nonzero'
            return
        props=scene.fluxfx
        thermal=2.0 if props.preview_channel=='FLAME' else float(props.preview_channel=='TEMPERATURE')
        self.render(solver.preview_field(props.preview_channel),transform,props.exposure,thermal,int(props.ray_steps))
