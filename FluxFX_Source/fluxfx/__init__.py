"""FluxFX dense reference and P1 native sparse infrastructure."""

bl_info = {
    "name": "FluxFX",
    "author": "FluxFX contributors",
    "version": (0, 41, 0),
    "blender": (5, 3, 0),
    "location": "3D View > Sidebar > FluxFX",
    "description": "Dense GPU smoke and native sparse brick prototype",
    "category": "Physics",
}


def register():
    from .blender.addon import register as register_addon
    register_addon()


def unregister():
    from .blender.addon import unregister as unregister_addon
    unregister_addon()
