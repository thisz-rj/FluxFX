"""Defensive device report: reported support is distinct from a tested path."""
from datetime import datetime, timezone
import platform


def collect(run_probe=False):
    import bpy
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "blender": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode(errors="replace"),
        "machine": platform.machine(), "os": platform.platform(),
        "background": bpy.app.background, "status": "BLOCKED", "errors": [],
        "probe_3d": {"status": "NOT_RUN"},
    }
    if bpy.app.background:
        report["errors"].append("No interactive GPU context: run diagnostics in a Blender window, not --background")
        return report
    import gpu

    def query(module, name, *args):
        try:
            return getattr(module, name)(*args)
        except Exception as exc:
            report["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
            return None

    report["device"] = {name: query(gpu.platform, function) for name, function in (
        ("backend", "backend_type_get"), ("type", "device_type_get"),
        ("renderer", "renderer_get"), ("vendor", "vendor_get"), ("driver", "version_get"))}
    report["capabilities"] = {name: query(gpu.capabilities, function) for name, function in (
        ("compute", "compute_shader_support_get"), ("image_load_store", "shader_image_load_store_support_get"),
        ("max_texture_size", "max_texture_size_get"), ("max_images", "max_images_get"))}
    caps = report["capabilities"]
    caps["max_work_group_size"] = [query(gpu.capabilities, "max_work_group_size_get", i) for i in range(3)]
    caps["max_work_group_count"] = [query(gpu.capabilities, "max_work_group_count_get", i) for i in range(3)]
    report["apple_silicon_metal"] = (report["machine"] == "arm64" and report["device"]["backend"] == "METAL")
    if bpy.app.version < (5, 3, 0):
        report["errors"].append("FluxFX targets Blender 5.3 or newer")
    elif caps["compute"] is True and caps["image_load_store"] is True:
        report["status"] = "CAPABLE_UNTESTED"
        if run_probe:
            try:
                from .device import BlenderGPUDevice
                report["probe_3d"] = BlenderGPUDevice().probe_3d()
                report["status"] = "READY"
            except Exception as exc:
                report["probe_3d"] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
                report["status"] = "BLOCKED"
    else:
        report["errors"].append("Compute/image support unavailable or could not be queried")
    return report
