import ast
from pathlib import Path
import unittest
from fluxfx.version import MANIFEST, VERSION, VERSION_LABEL, VERSION_TUPLE, _manifest_version

PACKAGE = Path(__file__).resolve().parents[1] / "fluxfx"


class VersionTests(unittest.TestCase):
    def test_manifest_is_the_single_source(self):
        self.assertEqual(VERSION_TUPLE, tuple(int(p) for p in VERSION.split(".")))
        self.assertEqual(VERSION_LABEL, f"{VERSION_TUPLE[0]}.{VERSION_TUPLE[1]}")

    def test_bl_info_literal_matches_manifest(self):
        tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
        info = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign) and node.targets[0].id == "bl_info")
        self.assertEqual(info["version"], VERSION_TUPLE)

    def test_fallback_parser_matches_tomllib(self):
        text = MANIFEST.read_text(encoding="utf-8")
        self.assertEqual(_manifest_version(text), VERSION)
        import re
        self.assertEqual(re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1), VERSION)

    def test_no_hard_coded_panel_version(self):
        source = (PACKAGE / "blender" / "addon.py").read_text(encoding="utf-8")
        self.assertNotIn(f'"FluxFX · {VERSION_LABEL}"', source)
        self.assertIn("VERSION_LABEL", source)


if __name__ == "__main__":
    unittest.main()
