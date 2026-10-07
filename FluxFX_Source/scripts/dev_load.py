"""Run from Blender's Text Editor for session-only development registration."""
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
# Loading over an enabled installed copy replaces its classes but leaves its
# handlers running, mixing two copies in one session: refuse instead.
installed = [name for name in bpy.context.preferences.addons.keys()
             if name.rsplit(".", 1)[-1] == "fluxfx" and name != "fluxfx"]
if installed or (hasattr(bpy.types.Scene, "fluxfx") and "fluxfx" not in sys.modules):
    raise RuntimeError("Another FluxFX copy is registered" + (f" ({installed[0]})" if installed else "")
                       + ": disable it in Preferences > Add-ons (or restart Blender) before loading from source")
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
