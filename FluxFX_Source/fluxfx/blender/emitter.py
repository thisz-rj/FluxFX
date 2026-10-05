"""Single spherical source controlled by an Empty in domain coordinates."""
from math import isfinite
import bpy
from mathutils import Vector
from .domain import domain_object,create_domain


def create_emitter(scene):
    obj=scene.fluxfx.emitter_object
    if obj is not None and obj.name in scene.objects:
        scene.fluxfx.source_mode='OBJECT'
        return obj
    domain=create_domain(scene)
    obj=bpy.data.objects.new('FluxFX Emitter',None)
    obj.empty_display_type='SPHERE'
    obj.empty_display_size=1.0
    obj.parent=domain
    obj.location=Vector(scene.fluxfx.source_center)-Vector((.5,.5,.5))
    obj.scale=(scene.fluxfx.source_radius,)*3
    obj['fluxfx_emitter']=True
    scene.collection.objects.link(obj)
    scene.fluxfx.emitter_object=obj
    scene.fluxfx.source_mode='OBJECT'
    return obj


def source_geometry(scene,props=None):
    props=props if props is not None else scene.fluxfx
    if props.source_mode=='MANUAL':
        return tuple(props.source_center),props.source_radius
    domain=domain_object(scene)
    emitter=props.emitter_object
    if domain is None:
        raise ValueError('Object emission requires a domain')
    if emitter is None or emitter.name not in scene.objects:
        raise ValueError('Emitter missing; assign an Empty or switch to Manual source')
    graph=bpy.context.evaluated_depsgraph_get()
    try:
        relative=domain.evaluated_get(graph).matrix_world.inverted() @ emitter.evaluated_get(graph).matrix_world
    except ValueError as exc:
        raise ValueError('Domain scale must be nonzero for object emission') from exc
    center=tuple(relative.translation+Vector((.5,.5,.5)))
    radius=max(relative.to_3x3().col[i].length for i in range(3))
    if not all(isfinite(v) for v in (*center,radius)) or radius<=1e-6:
        raise ValueError('Emitter transform must be finite with nonzero size')
    return center,radius


def emission_snapshot(scene,props=None):
    """Stable identity/domain placement plus evaluated local jet and frame."""
    props=props if props is not None else scene.fluxfx
    center,_=source_geometry(scene,props)
    jet=Vector(props.emission_velocity)
    key=(props.source_mode,props.emission_enabled)
    if props.source_mode=='OBJECT':
        graph=bpy.context.evaluated_depsgraph_get()
        domain=domain_object(scene).evaluated_get(graph).matrix_world
        emitter=props.emitter_object.evaluated_get(graph).matrix_world
        relative=domain.inverted() @ emitter
        # Orientation only: scaling changes the source size, not jet speed.
        jet=relative.to_quaternion() @ jet
        key+=(props.emitter_object.as_pointer(),tuple(v for row in domain for v in row))
    return center,tuple(jet),key,scene.frame_current+scene.frame_subframe


def prepare_emission(scene,previous,props=None,*,interval=None):
    from ..physics.emission import Emission,motion_velocity
    props=props if props is not None else scene.fluxfx
    current=emission_snapshot(scene,props)
    center,jet,key,frame=current
    compatible=(previous is not None and previous[2]==key and 0 <= frame-previous[3] <= 1)
    start=previous[0] if compatible else center
    if interval is None:
        interval=scene.fluxfx.time_step
        if compatible and frame>previous[3]:
            interval=(frame-previous[3])*scene.render.fps_base/scene.render.fps
    velocity=motion_velocity(start,center,interval,props.motion_inheritance,jet,props.motion_speed_limit)
    coupling=props.velocity_coupling if props.emission_enabled and (any(jet) or props.motion_inheritance>0) else 0.
    emission=Emission(start if props.continuous_trails and props.emission_enabled else center,velocity,coupling)
    return emission,current


def create_additional_emitter(scene):
    from uuid import uuid4
    props=scene.fluxfx
    if len(props.extra_emitters)>=7:
        raise ValueError("Maximum: primary source plus seven additional emitters")
    domain=create_domain(scene)
    obj=bpy.data.objects.new('FluxFX Emitter',None)
    obj.empty_display_type='SPHERE';obj.empty_display_size=1.;obj.parent=domain
    obj.location=Vector(props.source_center)-Vector((.5,.5,.5))
    obj.scale=(props.source_radius,)*3
    obj['fluxfx_emitter']=True
    scene.collection.objects.link(obj)
    entry=props.extra_emitters.add();entry.name=uuid4().hex;entry.emitter_object=obj
    return obj


def prepare_additional_sources(scene,history,*,interval=None):
    from ..physics.emission import Source
    sources=[];snapshots={}
    for entry in scene.fluxfx.extra_emitters:
        if not entry.emission_enabled:continue
        try:
            motion,snapshot=prepare_emission(scene,(history or {}).get(entry.name),entry,interval=interval)
            center,radius=source_geometry(scene,entry)
            sources.append(Source(center,radius,entry.source_rate,entry.heat_source_rate,motion,entry.density_mode,entry.source_profile,entry.fuel_source_rate))
            snapshots[entry.name]=snapshot
        except ValueError as exc:
            name=entry.emitter_object.name if entry.emitter_object else 'unassigned source'
            raise ValueError(f'Additional emitter {name}: {exc}') from exc
    return sources,snapshots
