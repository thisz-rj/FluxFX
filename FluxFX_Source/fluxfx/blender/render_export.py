"""OpenVDB export of baked caches and the Blender render volume they feed.

Workflow: Bake (optionally writing VDB alongside the cache) or Export VDB from
an existing cache -> one `.vdb` per baked frame in `<bake folder>/vdb/` ->
a Volume object parented to the domain, playing the sequence, with a
Principled Volume material: smoke from `density`; fire as blackbody emission
whose temperature and intensity follow the burn rate (`flame`), or whose
colour follows the exported absolute `temperature`, gated by `heat`. Colour is
Blender's own blackbody evaluation; nothing is baked to RGB. Cycles and EEVEE
render it like any Volume. All work runs on Blender's main thread; exports
are timer jobs like bakes. See docs/RENDER_EXPORT.md.
"""
from importlib import import_module
from pathlib import Path
import sys
import time
import bpy
from mathutils import Matrix
from ..physics.cache import CacheReader
from ..physics.volume_export import VDBSequenceWriter, frame_file, read_manifest, volume_sequence
from .domain import domain_object

FOLDER = 'vdb'
OBJECT_TAG = 'fluxfx_render_volume'
OBJECT_NAME = 'FluxFX Render Volume'
VOLUME_NAME = 'FluxFX Volume'
MATERIAL_NAME = 'FluxFX Smoke and Fire'
NODES = dict(output='FluxFX Output', principled='FluxFX Principled Volume', flame='FluxFX Flame',
             heat='FluxFX Heat', range='FluxFX Fire Range', kelvin='FluxFX Flame Kelvin',
             glow='FluxFX Fire Intensity')
EDGE_RATIO = 0.5  # flame edges (weakest burning) glow at this fraction of the core temperature


class OpenVDBUnavailable(RuntimeError):
    pass


class State:
    job = None
    message = ''
    progress = 0.0


STATE = State()
_openvdb = None


def openvdb():
    """Blender's bundled OpenVDB Python module (verified in Blender 5.2: OpenVDB 13)."""
    global _openvdb
    if _openvdb is not None:
        return _openvdb
    for name in ('openvdb', 'pyopenvdb'):
        try:
            _openvdb = import_module(name)
            return _openvdb
        except ImportError:
            pass
    # Blender-as-a-module keeps Blender's own site-packages off sys.path.
    folder = (Path(bpy.utils.resource_path('LOCAL')) / 'python' / 'lib' /
              f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages')
    if folder.is_dir() and str(folder) not in sys.path:
        sys.path.append(str(folder))
        try:
            _openvdb = import_module('openvdb')
            return _openvdb
        except ImportError:
            pass
    raise OpenVDBUnavailable('This Blender build has no OpenVDB Python module (openvdb); '
                             'VDB export needs Blender\'s bundled OpenVDB.')


def available():
    try:
        openvdb()
        return True
    except OpenVDBUnavailable:
        return False


def export_folder(cache_path):
    return Path(cache_path) / FOLDER


def sequence_writer(scene, cache_folder, shape, channels, start, end, fps, signature, provenance=None):
    """Writer for `<cache_folder>/vdb`, used during bakes and cache exports."""
    return VDBSequenceWriter(export_folder(cache_folder), shape, channels, start, end, fps, openvdb(),
                             ambient=scene.fluxfx.render_ambient,
                             source=dict(cache=str(cache_folder), signature=signature, provenance=provenance or {}),
                             producer=f'FluxFX {_version()}')


def _version():
    from ..version import VERSION
    return VERSION


# --- export from an existing cache -------------------------------------------------

class ExportJob:
    def __init__(self, scene, cache_path):
        self.scene = scene
        self.reader = CacheReader(bpy.path.abspath(cache_path))
        frames = sorted(int(f) for f in self.reader.meta['frames'])
        if not frames:
            raise ValueError('Cache has no completed frames to export')
        self.frames, self.next = frames, 0
        meta = self.reader.meta
        self.writer = sequence_writer(scene, self.reader.path, self.reader.grid.shape, meta['channels'],
                                      frames[0], frames[-1], meta['fps'], meta['signature'], meta.get('provenance'))
        self.started = time.perf_counter()

    def advance(self, budget=.05):
        deadline = time.perf_counter() + budget
        while self.next < len(self.frames):
            frame = self.frames[self.next]
            self.writer.write(frame, self.reader.read(frame))
            self.next += 1
            STATE.progress = self.next / len(self.frames)
            STATE.message = f'Exported VDB {self.next}/{len(self.frames)} frames'
            if time.perf_counter() >= deadline:
                return False
        self.writer.finish()
        STATE.message = (f'VDB export complete · {len(self.frames)} frames · '
                         f'{time.perf_counter() - self.started:.1f}s')
        return True


def start_export(scene):
    stop_export()
    if not scene.fluxfx.cache_path:
        raise ValueError('Choose a playback folder (a baked cache) to export')
    STATE.progress = 0.0
    STATE.job = ExportJob(scene, scene.fluxfx.cache_path)
    STATE.message = 'Exporting VDB sequence'
    bpy.app.timers.register(export_tick, first_interval=.01)


def stop_export(status='CANCELLED', message='VDB export cancelled; written frames kept'):
    job, STATE.job = STATE.job, None
    if bpy.app.timers.is_registered(export_tick):
        bpy.app.timers.unregister(export_tick)
    if job is not None:
        try:
            job.writer.finish(status, message)
        except Exception as exc:
            message += f'; could not update manifest: {exc}'
        STATE.message = message


def export_tick():
    job = STATE.job
    if job is None:
        return None
    try:
        if bpy.context.scene != job.scene:
            stop_export(message='VDB export cancelled after scene change')
            return None
        if job.advance():
            STATE.job = None
            if job.scene.fluxfx.render_auto_volume:
                ensure_render_volume(job.scene, job.writer.path)
            _redraw()
            return None
    except Exception as exc:
        stop_export('FAILED', str(exc))
        return None
    _redraw()
    return .01


def shutdown():
    stop_export()


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# --- render volume ------------------------------------------------------------------

def render_object(scene):
    for obj in scene.objects:
        if obj.get(OBJECT_TAG) and obj.type == 'VOLUME':
            return obj
    return None


def ensure_render_volume(scene, folder):
    """Create or update the Volume object playing the VDB sequence in `folder`."""
    folder = Path(folder)
    manifest = read_manifest(folder)
    count = len(manifest['frames'])
    if not count:
        raise ValueError('The VDB export has no frames yet')
    domain = domain_object(scene)
    if domain is None:
        raise ValueError('Create the FluxFX domain first; the render volume follows it')
    obj = render_object(scene)
    if obj is None:
        volume = bpy.data.volumes.new(VOLUME_NAME)
        obj = bpy.data.objects.new(OBJECT_NAME, volume)
        obj[OBJECT_TAG] = True
        scene.collection.objects.link(obj)
    volume = obj.data
    first = str(folder / frame_file(1))
    volume.filepath = bpy.path.relpath(first) if bpy.data.filepath else first
    for key, value in volume_sequence(manifest['start'], count).items():
        setattr(volume, key, value)
    volume.grids.unload()  # re-exports reuse file names inside a new bake folder; never show stale grids
    # Same space as the preview: the VDB transform targets the domain's [-0.5, 0.5]^3 box.
    obj.parent = domain
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = Matrix.Identity(4)
    obj['fluxfx_export'] = str(folder)
    material = ensure_material(volume)
    if material is not None:
        apply_material_settings(material, scene.fluxfx, manifest)
    return obj


def ensure_material(volume):
    """FluxFX's material on `volume`; None when the user assigned their own."""
    material = next((m for m in volume.materials if m is not None and m.get('fluxfx_material')), None)
    if material is None:
        if any(m is not None for m in volume.materials):
            return None  # a custom shader stays untouched by bakes and settings
        material = bpy.data.materials.get(MATERIAL_NAME)
        if material is None or not material.get('fluxfx_material'):
            material = bpy.data.materials.new(MATERIAL_NAME)
            material['fluxfx_material'] = True
        volume.materials.clear()
        volume.materials.append(material)
    if not all(name in material.node_tree.nodes for name in NODES.values()):
        build_material(material)
    return material


def build_material(material):
    """Node tree: smoke = density x scale; fire = Principled Volume blackbody.

    A normalised fire amount f = clamp(source / reference) scales the blackbody
    intensity (f x fire intensity), so emission fades out where nothing burns.
    Flame mode: source = burn rate, and f also sets the temperature (edges at
    EDGE_RATIO x core, core at the flame temperature). Temperature mode:
    source = heat (excess over ambient) and the temperature is the exported
    absolute `temperature` grid; gating by heat keeps ambient air dark, which
    Cycles would otherwise tint red (its blackbody colour is constant below
    800 K). Colour always comes from Blender's own blackbody evaluation.
    """
    if material.node_tree is None:
        material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    output.name = output.label = NODES['output']
    output.is_active_output = True  # a new output is not active by default
    output.location = (600, 0)
    principled = tree.nodes.new('ShaderNodeVolumePrincipled')
    principled.name = principled.label = NODES['principled']
    principled.location = (300, 0)
    flame = tree.nodes.new('ShaderNodeAttribute')
    flame.name, flame.label = NODES['flame'], 'Flame (fuel/s)'
    flame.attribute_type, flame.attribute_name = 'GEOMETRY', 'flame'
    flame.location = (-560, -160)
    heat = tree.nodes.new('ShaderNodeAttribute')
    heat.name, heat.label = NODES['heat'], 'Heat (K above ambient)'
    heat.attribute_type, heat.attribute_name = 'GEOMETRY', 'heat'
    heat.location = (-560, -360)
    span = tree.nodes.new('ShaderNodeMapRange')
    span.name, span.label = NODES['range'], 'Fire 0..1'
    span.clamp = True
    span.location = (-340, -200)
    kelvin = tree.nodes.new('ShaderNodeMapRange')
    kelvin.name, kelvin.label = NODES['kelvin'], 'Flame temperature (K)'
    kelvin.clamp = True
    kelvin.location = (-100, -120)
    glow = tree.nodes.new('ShaderNodeMath')
    glow.name, glow.label = NODES['glow'], 'Blackbody intensity'
    glow.operation = 'MULTIPLY'
    glow.use_clamp = False  # intensities above 1 are valid; only the socket's own field is capped
    glow.location = (-100, -360)
    links = tree.links
    links.new(principled.outputs['Volume'], output.inputs['Volume'])
    links.new(span.outputs['Result'], kelvin.inputs['Value'])
    links.new(span.outputs['Result'], glow.inputs[0])
    links.new(glow.outputs['Value'], principled.inputs['Blackbody Intensity'])
    return material


def _unlink(tree, socket):
    for link in list(socket.links):
        tree.links.remove(link)


def apply_material_settings(material, props, manifest=None):
    """Push the panel's render settings into the named nodes; user edits elsewhere stay."""
    tree = material.node_tree
    nodes = tree.nodes
    principled, span = nodes[NODES['principled']], nodes[NODES['range']]
    kelvin, glow = nodes[NODES['kelvin']], nodes[NODES['glow']]
    principled.inputs['Color'].default_value = (*props.render_smoke_color, 1.0)
    principled.inputs['Density'].default_value = props.render_density
    principled.inputs['Density Attribute'].default_value = 'density'
    mode = props.render_fire_mode
    ranges = (manifest or {}).get('ranges', {})
    source = 'heat' if mode == 'TEMPERATURE' else 'flame'
    highest = (ranges.get(source) or {}).get('max', 0.0)
    reference = (props.render_flame_reference if source == 'flame' else 0.0) or highest or 1.0
    _unlink(tree, span.inputs['Value'])
    tree.links.new(nodes[NODES[source]].outputs['Fac'], span.inputs['Value'])
    span.inputs['From Min'].default_value, span.inputs['From Max'].default_value = 0.0, reference
    span.inputs['To Min'].default_value, span.inputs['To Max'].default_value = 0.0, 1.0
    core = props.render_flame_temperature
    kelvin.inputs['From Min'].default_value, kelvin.inputs['From Max'].default_value = 0.0, 1.0
    kelvin.inputs['To Min'].default_value, kelvin.inputs['To Max'].default_value = EDGE_RATIO * core, core
    glow.inputs[1].default_value = props.render_fire_intensity
    temperature, intensity = principled.inputs['Temperature'], principled.inputs['Blackbody Intensity']
    _unlink(tree, temperature)
    _unlink(tree, intensity)
    if mode == 'FLAME':
        principled.inputs['Temperature Attribute'].default_value = ''
        tree.links.new(kelvin.outputs['Result'], temperature)
    else:
        principled.inputs['Temperature Attribute'].default_value = 'temperature'  # exported in kelvin
        temperature.default_value = 1.0
    if mode == 'NONE':
        intensity.default_value = 0.0
    else:
        tree.links.new(glow.outputs['Value'], intensity)
    return dict(mode=mode, source=source, reference=reference)


def update_material(scene):
    obj = render_object(scene)
    if obj is None:
        raise ValueError('No FluxFX render volume yet; bake with VDB or export one first')
    material = ensure_material(obj.data)
    if material is None:
        raise ValueError('The render volume uses a custom material; FluxFX render settings do not apply to it')
    folder = obj.get('fluxfx_export')
    manifest = read_manifest(folder) if folder and Path(folder).is_dir() else None
    return apply_material_settings(material, scene.fluxfx, manifest)
