"""Small GPU boundary. No bpy dependency and no fallback fluid loops."""
from math import isfinite, prod
from pathlib import Path

from ..physics.config import workgroups

LOCAL_SIZE = (4, 4, 4)
SHADERS = Path(__file__).resolve().parents[1] / "shaders"


class GPUUnavailable(RuntimeError):
    pass


class BlenderGPUDevice:
    def __init__(self):
        import gpu
        self.gpu = gpu
        caps = gpu.capabilities
        try:
            if not caps.compute_shader_support_get() or not caps.shader_image_load_store_support_get():
                raise GPUUnavailable("Compute shaders and image load/store are required")
            self.max_groups = tuple(caps.max_work_group_count_get(i) for i in range(3))
            max_local = tuple(caps.max_work_group_size_get(i) for i in range(3))
            if any(a > b for a, b in zip(LOCAL_SIZE, max_local)):
                raise GPUUnavailable("Device cannot run the P0 4×4×4 workgroup")
        except Exception as exc:
            raise GPUUnavailable(f"GPU context/capability check failed: {exc}") from exc

    def texture(self, shape, values=None, *, nonnegative=True, channels=1):
        if channels not in (1,4):raise ValueError("Only scalar or four-channel fields are supported")
        data = None
        if values is not None:
            if len(values) != prod(shape)*channels or not all(isfinite(v) and (not nonnegative or v >= 0) for v in values):
                raise ValueError("Field upload must match grid and satisfy finite/sign constraints")
            data = self.gpu.types.Buffer("FLOAT", prod(shape)*channels, values)
        tex = self.gpu.types.GPUTexture(shape, format="RGBA32F" if channels==4 else "R32F", data=data)
        tex.filter_mode(False)
        if data is None:
            tex.clear(format="FLOAT", value=(0.0,)*channels)
        return tex

    def kernel(self, filename, constants=(), sample_input=False, samplers=(), includes=(), output_format="R32F"):
        info = self.gpu.types.GPUShaderCreateInfo()
        info.local_group_size(*LOCAL_SIZE)
        info.image(0, output_format, "FLOAT_3D", "outputField", qualifiers={"WRITE"})
        if sample_input:
            info.sampler(0, "FLOAT_3D", "inputField")
        for slot, name in enumerate(samplers, start=1):
            info.sampler(slot, "FLOAT_3D", name)
        info.push_constant("IVEC3", "gridSize")
        for kind, name in constants:
            info.push_constant(kind, name)
        info.compute_source("\n".join((SHADERS / name).read_text() for name in (*includes, filename)))
        return self.gpu.shader.create_from_info(info)

    def dispatch(self, shader, output, shape, uniforms=None, input_field=None, sources=None):
        groups = workgroups(shape, LOCAL_SIZE)
        if any(g > limit for g, limit in zip(groups, self.max_groups)):
            raise GPUUnavailable(f"Dispatch {groups} exceeds device limits {self.max_groups}")
        if output is input_field or any(output is tex for tex in (sources or {}).values()):
            raise ValueError("Advection input/output textures must be distinct")
        shader.bind()
        shader.uniform_int("gridSize", shape)
        shader.image("outputField", output)
        if input_field is not None:
            shader.uniform_sampler("inputField", input_field)
        for name, texture in (sources or {}).items():
            shader.uniform_sampler(name, texture)
        for name, value in (uniforms or {}).items():
            shader.uniform_float(name, value)
        # Blender's Python dispatch inserts image-access + texture-fetch barriers.
        # Do not invent gpu.memory_barrier(): it is not a public Python API.
        self.gpu.compute.dispatch(shader, *groups)

    @staticmethod
    def read(texture, shape):
        """Synchronous readback: diagnostics, tests, or tiny adaptive-step reductions."""
        buffer = texture.read()
        buffer.dimensions = (prod(shape),)
        return list(buffer)

    def probe_3d(self):
        shape = (7, 5, 3)  # deliberately non-cubic and not workgroup-aligned
        texture = self.texture(shape)
        kernel = self.kernel("probe.glsl")
        self.dispatch(kernel, texture, shape)
        actual = self.read(texture, shape)
        expected = [float(x + 10 * y + 100 * z)
                    for z in range(3) for y in range(5) for x in range(7)]
        error = max(abs(a - b) for a, b in zip(actual, expected))
        if not all(isfinite(v) for v in actual) or error > 1e-6:
            raise GPUUnavailable(f"R32F 3D image-store/readback mismatch: {error}")
        return {"status": "PASS", "format": "R32F", "shape": shape,
                "texels_checked": len(actual), "max_abs_error": error}
