"""Single version source: the extension manifest beside this package.

`bl_info` in `__init__.py` must stay a literal for Blender's legacy add-on
parser; tests assert it matches this value. Packaging and the UI read here.
"""
from pathlib import Path
import re

MANIFEST = Path(__file__).resolve().with_name("blender_manifest.toml")


def _manifest_version(text):
    try:
        import tomllib
    except ImportError:  # Python < 3.11; Blender 5.3 bundles 3.13
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if match is None:
            raise ValueError("blender_manifest.toml has no version")
        return match.group(1)
    return tomllib.loads(text)["version"]


VERSION = _manifest_version(MANIFEST.read_text(encoding="utf-8"))
VERSION_TUPLE = tuple(int(part) for part in VERSION.split(".")[:3])
VERSION_LABEL = ".".join(VERSION.split(".")[:2])
