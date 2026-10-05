"""Blender object placement for static analytic collider snapshots."""
from uuid import uuid4
import bpy
from mathutils import Matrix
from .domain import create_domain, domain_object
from ..physics.collision import Collider
from ..physics.mesh import MeshCollider


def create_collider(scene, shape):
    if shape not in ('SPHERE','BOX'): raise ValueError('Choose Sphere or Box')
    if len(scene.fluxfx.colliders)>=8: raise ValueError('Maximum eight collider entries')
    domain = create_domain(scene)
    obj = bpy.data.objects.new('FluxFX '+shape.title()+' Collider',None)
    obj.empty_display_type = 'SPHERE' if shape=='SPHERE' else 'CUBE'
    obj.empty_display_size = 1.0
    obj.parent = domain
    obj.location = (0,0,0)
    obj.scale = (.18,.18,.12) if shape=='BOX' else (.18,)*3
    obj['fluxfx_collider'] = True
    scene.collection.objects.link(obj)
    entry = scene.fluxfx.colliders.add()
    entry.name = uuid4().hex
    entry.shape = shape
    entry.collider_object = obj
    return obj


def collider_snapshot(scene):
    entries = [entry for entry in scene.fluxfx.colliders if entry.enabled]
    if not entries: return ()
    if len(entries)>8: raise ValueError('Maximum eight enabled colliders')
    domain = domain_object(scene)
    if domain is None: raise ValueError('Colliders require a smoke domain')
    graph = bpy.context.evaluated_depsgraph_get()
    world = domain.evaluated_get(graph).matrix_world
    if abs(world.determinant())<1e-12: raise ValueError('Domain scale must be nonzero')
    simulation_to_world = world @ Matrix.Translation((-.5,-.5,-.5))
    result=[]
    for entry in entries:
        obj = entry.collider_object
        if obj is None or obj.name not in scene.objects:
            raise ValueError('Collider missing; assign an object or disable its entry, then Reset')
        evaluated=obj.evaluated_get(graph)
        matrix = evaluated.matrix_world
        if entry.shape=='MESH':
            if scene.fluxfx.moving_colliders:raise ValueError('Mesh colliders are static; disable Moving colliders and Reset')
            if obj.type!='MESH':raise ValueError('Mesh collider requires a Mesh object')
            if obj.mode=='EDIT':raise ValueError('Leave Edit Mode, then Reset mesh collisions')
            if abs(matrix.determinant())<1e-12:raise ValueError('Mesh scale must be nonzero')
            mesh=evaluated.to_mesh()
            try:
                mesh.calc_loop_triangles()
                if len(mesh.loop_triangles)>50000:raise ValueError('Mesh collider limit: 50,000 evaluated triangles')
                transform=simulation_to_world.inverted() @ matrix
                vertices=tuple(tuple(round(float(c),7) for c in transform @ v.co) for v in mesh.vertices)
                triangles=tuple(tuple(t.vertices) for t in mesh.loop_triangles)
                result.append(MeshCollider(vertices,triangles))
            finally:evaluated.to_mesh_clear()
            continue
        if obj.type!='EMPTY':raise ValueError('Sphere/Box collider requires an Empty; choose Mesh for a mesh object')
        if abs(matrix.determinant())<1e-12: raise ValueError('Collider scale must be nonzero')
        inverse = matrix.inverted() @ simulation_to_world
        # Ignore numerical noise when domain and its children move together.
        rows = tuple(tuple(round(float(v),7) for v in inverse[i]) for i in range(3))
        result.append(Collider(entry.shape,rows))
    return tuple(result)


def update_display_shape(entry, _context):
    obj=entry.collider_object
    if obj is not None and obj.type=='EMPTY' and obj.get('fluxfx_collider'):
        obj.empty_display_type='SPHERE' if entry.shape=='SPHERE' else 'CUBE'
        obj.empty_display_size=1.0


def collider_bindings(scene):
    """Stable enabled-entry identities; changing ownership requires Reset."""
    return tuple((e.name,e.shape,e.collider_object.as_pointer() if e.collider_object else 0)
                 for e in scene.fluxfx.colliders if e.enabled)
