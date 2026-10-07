"""Capability claims must never bypass failed or missing GPU verification."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fluxfx.backend.diagnostics import collect
from fluxfx.backend.device import BlenderGPUDevice


class DiagnosticTests(unittest.TestCase):
    def modules(self, background=False, compute=True):
        bpy = SimpleNamespace(app=SimpleNamespace(background=background, version=(5, 3, 0),
                                                   version_string="test", build_hash=b"test"))
        platform = SimpleNamespace(**{name: (lambda value=value: value) for name, value in {
            "backend_type_get": "METAL", "device_type_get": "APPLE", "renderer_get": "test",
            "vendor_get": "test", "version_get": "test"}.items()})
        caps = SimpleNamespace(compute_shader_support_get=lambda: compute,
                               shader_image_load_store_support_get=lambda: True,
                               max_texture_size_get=lambda: 16384, max_images_get=lambda: 64,
                               max_work_group_size_get=lambda i: 1024,
                               max_work_group_count_get=lambda i: 65535)
        return {"bpy": bpy, "gpu": SimpleNamespace(platform=platform, capabilities=caps)}

    def test_background_never_probes(self):
        with patch.dict(sys.modules, self.modules(background=True)), patch.object(BlenderGPUDevice, "probe_3d") as probe:
            report = collect(True)
            self.assertEqual(report["status"], "BLOCKED")
            probe.assert_not_called()

    def test_reported_support_is_not_ready(self):
        with patch.dict(sys.modules, self.modules()):
            self.assertEqual(collect()["status"], "CAPABLE_UNTESTED")

    def test_failed_probe_blocks(self):
        with patch.dict(sys.modules, self.modules()), patch.object(BlenderGPUDevice, "probe_3d", side_effect=RuntimeError("compile failed")):
            report = collect(True)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("compile failed", report["probe_3d"]["error"])

    def test_missing_function_is_reported(self):
        modules = self.modules()
        del modules["gpu"].capabilities.compute_shader_support_get
        with patch.dict(sys.modules, modules):
            report = collect(True)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIsNone(report["capabilities"]["compute"])
            self.assertTrue(report["errors"])

    def test_unsupported_compute_blocks(self):
        with patch.dict(sys.modules, self.modules(compute=False)):
            self.assertEqual(collect(True)["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
