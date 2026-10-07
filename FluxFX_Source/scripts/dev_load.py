"""Run from Blender's Text Editor for session-only development registration."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import fluxfx

# Safe to run this loader repeatedly; stop handlers before unloading modules.
fluxfx.unregister()
for name in list(sys.modules):
    if name == "fluxfx" or name.startswith("fluxfx."):
        del sys.modules[name]
import fluxfx
fluxfx.register()
print("FluxFX ready. Open 3D View > Sidebar (N) > FluxFX.")
