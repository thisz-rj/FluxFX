"""GPU-only slice and orthographic volume inset; no scene depth compositing."""
from pathlib import Path
from mathutils import Vector
import bpy
import gpu
from gpu_extras.batch import batch_for_shader


class SlicePreview:
    def __init__(self, volume=False):
        self.volume = volume
        interface = gpu.types.GPUStageInterfaceInfo("fluxfx_slice_interface")
        interface.smooth("VEC2", "sliceUV")
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC2", "position")
        info.vertex_out(interface)
        info.push_constant("VEC2", "viewportSize")
        info.push_constant("FLOAT", "uiScale")
        info.push_constant("FLOAT", "sliceY")
        info.push_constant("FLOAT", "exposure")
        info.push_constant("FLOAT", "thermalView")
        if volume:
            for name in ("viewRight", "viewUp", "viewForward"):
                info.push_constant("VEC3", name)
            info.push_constant("INT", "raySteps")
        info.sampler(0, "FLOAT_3D", "densityField")
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source('''
void main() {
    sliceUV = position;
    float side = max(32.0, min(260.0 * uiScale, min(viewportSize.x - 48.0 * uiScale, viewportSize.y - 96.0 * uiScale)));
    vec2 pixel = vec2(24.0, 48.0) * uiScale + position * side;
    gl_Position = vec4(pixel / viewportSize * 2.0 - 1.0, 0.0, 1.0);
}''')
        slice_fragment = '''
void main() {
    float value = texture(densityField, vec3(sliceUV.x, sliceY, sliceUV.y)).r;
    float d = (thermalView > 0.5 && thermalView < 1.5) ? abs(value) / 100.0 : max(value, 0.0);
    float opacity = 1.0 - exp(-exposure * d);
    vec3 bg = vec3(0.018, 0.029, 0.044);
    vec3 smoke = thermalView>1.5 ? mix(vec3(1.0,0.12,0.01),vec3(1.0,0.9,0.45),clamp(value/4.0,0.0,1.0)) : thermalView > 0.5 ? (value >= 0.0 ? vec3(1.0, 0.35, 0.08) : vec3(0.1, 0.4, 1.0)) : vec3(0.67, 0.84, 0.94);
    fragColor = vec4(mix(bg, smoke, opacity), 1.0);
}'''
        info.fragment_source(''.join((Path(__file__).resolve().parents[1] / 'shaders' / name).read_text() for name in ('field_sample.glsl', 'volume.frag.glsl')) if volume else slice_fragment)
        self.shader = gpu.shader.create_from_info(info)
        self.batch = batch_for_shader(self.shader, "TRI_FAN",
                                      {"position": ((0, 0), (1, 0), (1, 1), (0, 1))})

    def draw(self, solver, slice_y, exposure, channel="DENSITY", ray_steps=128):
        region = bpy.context.region
        previous = (gpu.state.blend_get(), gpu.state.depth_test_get(), gpu.state.depth_mask_get())
        try:
            gpu.state.blend_set("NONE")
            gpu.state.depth_test_set("NONE")
            gpu.state.depth_mask_set(False)
            self.shader.bind()
            self.shader.uniform_float("viewportSize", (region.width, region.height))
            self.shader.uniform_float("uiScale", bpy.context.preferences.system.ui_scale)
            if self.volume:
                rotation = bpy.context.region_data.view_rotation
                for name, axis in (("viewRight", (1,0,0)), ("viewUp", (0,1,0)), ("viewForward", (0,0,-1))):
                    self.shader.uniform_float(name, rotation @ Vector(axis))
                self.shader.uniform_int("raySteps", ray_steps)
            else:
                self.shader.uniform_float("sliceY", slice_y)
            self.shader.uniform_float("exposure", exposure)
            self.shader.uniform_float("thermalView", 2.0 if channel == "FLAME" else (1.0 if channel == "TEMPERATURE" else 0.0))
            self.shader.uniform_sampler("densityField", solver.preview_field(channel))
            self.batch.draw(self.shader)
        finally:
            gpu.state.blend_set(previous[0])
            gpu.state.depth_test_set(previous[1])
            gpu.state.depth_mask_set(previous[2])
