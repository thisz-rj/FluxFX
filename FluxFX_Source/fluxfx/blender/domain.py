"""A scene-owned Empty places a unit simulation domain; never owns GPU state."""
import bpy
from mathutils import Matrix


def domain_object(scene):
    obj=scene.fluxfx.domain_object
    return obj if obj is not None and obj.name in scene.objects else None


def create_domain(scene):
    existing=domain_object(scene)
    if existing is not None:
        return existing
    obj=bpy.data.objects.new('FluxFX Domain',None)
    obj.empty_display_type='CUBE'
    obj.empty_display_size=0.5
    obj.location=(0,0,0.5)
    obj['fluxfx_domain']=True
    scene.collection.objects.link(obj)
    scene.fluxfx.domain_object=obj
    return obj


def clip_to_domain(view_projection, matrix_world):
    # Cube Empty spans [-.5,.5]; simulation coordinates span [0,1].
    transform=matrix_world @ Matrix.Translation((-0.5,-0.5,-0.5))
    return (view_projection @ transform).inverted()
