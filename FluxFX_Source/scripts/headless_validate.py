"""Headless Blender validation: FluxFX's real GPU solver and Blender integration
without a window.

Runs inside Blender-as-a-Python-module (`bpy`) with an EGL GPU context: a
hardware GPU, or Mesa llvmpipe in software on Linux CI. It exercises code the
standalone unit suite cannot reach: GPU baking, cache playback validation,
the invalid-value guard and volume export/rendering.

    pip install bpy==5.2.2 numpy        # Python 3.13; Blender 5.3 when published
    EGL_PLATFORM=surfaceless python3.13 scripts/headless_validate.py --output report.json

(Linux needs Mesa's EGL/llvmpipe, e.g. apt install libegl1 libegl-mesa0
libgl1-mesa-dri; CI runs exactly this on every push.)

or with an installed Blender (Metal on Apple Silicon), without a window:

    blender --background --factory-startup --python scripts/headless_validate.py -- --output report.json

or inside an already running graphical Blender (when no new Blender process
can be launched). Disable the installed FluxFX add-on first, then in the
Python Console:

    import runpy
    suite = runpy.run_path('/path/to/FluxFX_Source/scripts/headless_validate.py', run_name='fluxfx_validation')
    report = suite['run_in_session']('--output', '/tmp/fluxfx-042.json', '--workdir', '/tmp/fluxfx-042')

In-session runs never reset the file: checks work in a temporary scene, the
windows return to their scenes afterwards, every data-block the checks
created is removed and FluxFX (registered from this source tree) is
unregistered again. Bake folders and renders stay in --workdir.

`--full` adds the slow exit-criteria check (128^3 fire, 120 frames, VDB,
Cycles renders, copy-overhead share; several GiB in --workdir).

Limits: timers and draw handlers are not driven by an event loop, so the
harness calls the same functions the timers would. Blender older than the
manifest minimum is registered with the version gate bypassed and reported as
such. Exit status is nonzero if any check fails.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHECKS = []
SLOW = set()


def check(function=None, *, slow=False):
    """Register a check; slow checks run only with --full or a matching -k."""
    def add(function):
        CHECKS.append(function)
        if slow:
            SLOW.add(function.__name__)
        return function
    return add(function) if function is not None else add


def leftover_registration():
    """This source tree's add-on module, if an earlier load left its classes registered."""
    source = sys.modules.get('fluxfx')
    if source is None or Path(source.__file__).resolve().parent != ROOT / 'fluxfx':
        return None
    from fluxfx.blender import addon
    return addon if any('bl_rna' in cls.__dict__ for cls in addon.CLASSES) else None


def setup_blender(in_session=False):
    import bpy
    import gpu
    if in_session:
        leftover = leftover_registration()
        if hasattr(bpy.types.Scene, 'fluxfx'):
            hint = ('FluxFX from this source tree is loaded (dev_load): run `import fluxfx; fluxfx.unregister()`'
                    if leftover else 'disable the installed add-on (Preferences > Add-ons)')
            raise RuntimeError(f'FluxFX is already registered in this session. {hint}, then run again')
        if leftover:
            # Disabling another copy deletes Scene.fluxfx but not this tree's classes from an earlier load.
            leftover.unregister()
    else:
        gpu.init()
        bpy.ops.wm.read_factory_settings(use_empty=True)
    import fluxfx
    from fluxfx.version import VERSION_TUPLE
    info = dict(blender=bpy.app.version_string, backend=gpu.platform.backend_type_get(),
                renderer=gpu.platform.renderer_get(), fluxfx=fluxfx.bl_info['version'])
    minimum = fluxfx.bl_info['blender']
    if bpy.app.version >= minimum:
        fluxfx.register()
        info['registration'] = 'register()'
    else:
        # Same steps as blender.addon.register, minus its Blender-version gate.
        from fluxfx.blender import addon, runtime, cache, invalidation
        for cls in addon.CLASSES:
            bpy.utils.register_class(cls)
        bpy.types.Scene.fluxfx = bpy.props.PointerProperty(type=addon.FluxFXProperties)
        bpy.app.handlers.load_pre.append(runtime.before_load)
        bpy.app.handlers.frame_change_post.append(cache.frame_changed)
        bpy.app.handlers.depsgraph_update_post.append(bpy.app.handlers.persistent(invalidation.depsgraph_updated))
        info['registration'] = f'version gate bypassed: Blender {bpy.app.version_string} < {minimum}'
    assert VERSION_TUPLE == tuple(fluxfx.bl_info['version'])
    return info


def teardown_blender():
    from fluxfx.blender import addon
    addon.unregister()


class SessionSandbox:
    """A temporary scene in a live session; everything created inside is removed on exit."""
    def __enter__(self):
        import bpy
        self.before = {id_.as_pointer() for id_ in bpy.data.user_map()}
        self.windows = [(window, window.scene) for window in bpy.context.window_manager.windows]
        self.scene = bpy.data.scenes.new('FluxFX validation (temporary)')
        for window, _ in self.windows:
            window.scene = self.scene
        return self

    def __exit__(self, *_exc):
        import bpy
        for window, scene in self.windows:
            window.scene = scene
        created = [id_ for id_ in bpy.data.user_map() if id_.as_pointer() not in self.before]
        bpy.data.batch_remove(created)
        self.removed = len(created)
        return False


def fresh_scene(folder, resolution='16', start=1, end=6):
    import bpy
    from fluxfx.blender.domain import create_domain
    from fluxfx.blender.emitter import create_emitter
    from fluxfx.blender import cache, runtime
    runtime.shutdown()
    scene = bpy.context.scene
    for obj in list(scene.objects):  # only this scene's: in-session runs share the file
        bpy.data.objects.remove(obj)
    props = scene.fluxfx
    props.resolution = resolution
    props.cache_directory = str(folder)
    props.cache_start, props.cache_end = start, end
    props.cache_animated = False
    scene.render.fps = 24
    scene.frame_set(start)
    create_domain(scene)
    emitter = create_emitter(scene)
    bpy.context.view_layer.update()
    cache.STATE.message = ''
    return scene, emitter


def bake(scene):
    """Drive the real bake timer callback until the job finishes."""
    from fluxfx.blender import cache
    cache.start_bake(scene)
    ticks = 0
    while cache.STATE.job is not None:
        cache.bake_tick()
        ticks += 1
    if not cache.STATE.message.startswith('Bake complete'):
        raise AssertionError(f'Bake failed: {cache.STATE.message}')
    return ticks


class Timer:
    """Wrap a module function or method and record the duration of each call."""
    def __init__(self, owner, name):
        self.owner, self.name, self.seconds = owner, name, []
        self.original = getattr(owner, name)

        def timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                return self.original(*args, **kwargs)
            finally:
                self.seconds.append(time.perf_counter() - start)
        setattr(owner, name, timed)

    def restore(self):
        setattr(self.owner, self.name, self.original)

    def median_ms(self):
        import statistics
        return round(1000 * statistics.median(self.seconds), 2) if self.seconds else None


class Counter:
    """Wrap a module function and count calls."""
    def __init__(self, module, name):
        self.module, self.name, self.calls = module, name, 0
        self.original = getattr(module, name)

        def counted(*args, **kwargs):
            self.calls += 1
            return self.original(*args, **kwargs)
        setattr(module, name, counted)

    def restore(self):
        setattr(self.module, self.name, self.original)


def ticks(count):
    from fluxfx.blender import cache
    start = time.perf_counter()
    for _ in range(count):
        cache.playback_tick()
    return (time.perf_counter() - start) / count * 1000


@check
def fixed_cache_playback_fingerprints_only_after_changes(folder):
    import bpy
    from fluxfx.blender import cache
    scene, emitter = fresh_scene(folder / 'fixed')
    bake(scene)
    cache.load_cache(scene)
    snapshots = Counter(cache, 'snapshot')
    try:
        idle_ms = ticks(300)
        idle = snapshots.calls
        assert cache.STATE.frame == scene.frame_current, cache.STATE.message
        assert idle <= 1, f'idle ticks fingerprinted {idle} times'
        for frame in range(scene.fluxfx.cache_start, scene.fluxfx.cache_end + 1):
            scene.frame_set(frame); cache.playback_tick()
        first_pass = snapshots.calls - idle
        for frame in range(scene.fluxfx.cache_start, scene.fluxfx.cache_end + 1):
            scene.frame_set(frame); cache.playback_tick()
        second_pass = snapshots.calls - idle - first_pass
        assert second_pass == 0, f'revisited frames fingerprinted {second_pass} times'
        emitter.location.x += 0.05; bpy.context.view_layer.update(); cache.playback_tick()
        assert cache.STATE.frame is None and 'outdated' in cache.STATE.message, 'moved emitter not detected'
        emitter.location.x -= 0.05; bpy.context.view_layer.update(); cache.playback_tick()
        assert cache.STATE.frame == scene.frame_current, f'restored emitter not accepted: {cache.STATE.message}'
        scene.fluxfx.source_rate += 1.0; cache.playback_tick()
        assert cache.STATE.frame is None, 'property edit not detected'
        scene.fluxfx.source_rate -= 1.0; cache.playback_tick()
        assert cache.STATE.frame == scene.frame_current, 'restored property not accepted'
        scene.fluxfx.exposure += 1.0; before = snapshots.calls; ticks(50)
        assert snapshots.calls == before, 'display-only edit triggered fingerprinting'
        return dict(idle_ticks=300, idle_fingerprints=idle, idle_tick_ms=round(idle_ms, 4),
                    first_timeline_pass_fingerprints=first_pass, second_pass_fingerprints=second_pass,
                    legacy_fingerprints_for_same_ticks=300 + 2 * (scene.fluxfx.cache_end - scene.fluxfx.cache_start + 1))
    finally:
        snapshots.restore()
        cache.shutdown()


@check
def animated_cache_playback_fingerprints_once_per_frame(folder):
    from fluxfx.blender import cache
    scene, emitter = fresh_scene(folder / 'animated')
    emitter.location.x = -0.2; emitter.keyframe_insert('location', frame=1)
    emitter.location.x = 0.2; emitter.keyframe_insert('location', frame=6)
    scene.fluxfx.cache_animated = True
    bake(scene)
    cache.load_cache(scene)
    snapshots, signatures = Counter(cache, 'snapshot'), Counter(cache, 'animation_signature')
    try:
        ticks(100)
        idle = (snapshots.calls, signatures.calls)
        for _ in range(2):
            for frame in range(1, 7):
                scene.frame_set(frame); cache.playback_tick()
                assert cache.STATE.frame == frame, cache.STATE.message
        assert snapshots.calls - idle[0] <= 6, f'{snapshots.calls - idle[0]} snapshots for 6 frames twice'
        assert signatures.calls <= 1, f'animation signature computed {signatures.calls} times'
        played = dict(snapshots=snapshots.calls, animation_signatures=signatures.calls)
        emitter.location.x = 0.35; emitter.keyframe_insert('location', frame=6)  # edit the animation
        import bpy
        bpy.context.view_layer.update(); cache.playback_tick()
        assert cache.STATE.frame is None and 'outdated' in cache.STATE.message, 'keyframe edit not detected'
        return dict(idle_ticks=100, idle_fingerprints=idle[0], frames_played=12, **played,
                    keyframe_edit_detected=True)
    finally:
        snapshots.restore(); signatures.restore()
        cache.shutdown()


@check
def bake_does_not_refingerprint_every_tick(folder):
    from fluxfx.blender import cache
    scene, _ = fresh_scene(folder / 'bake_ticks', end=4)
    snapshots = Counter(cache, 'snapshot')
    try:
        bake_ticks = bake(scene)
        # 0.41: one snapshot at start plus one per bake tick.
        assert snapshots.calls <= 2, f'{snapshots.calls} snapshots over {bake_ticks} bake ticks'
        return dict(bake_ticks=bake_ticks, snapshots=snapshots.calls, legacy_snapshots=1 + bake_ticks)
    finally:
        snapshots.restore()


def poisoned_texture(shape, index, value):
    import gpu
    from math import prod
    values = [0.0] * prod(shape)
    values[index] = value
    return gpu.types.GPUTexture(shape, format='R32F', data=gpu.types.Buffer('FLOAT', len(values), values))


@check
def step_guard_detects_invalid_values_anywhere(folder):
    import math
    from math import prod
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.completion import StepCompletion, SimulationFault
    grid = GridSpec((16, 16, 16))
    settings = PressureSettings(combustion_enabled=True, velocity_advection='MACCORMACK', scalar_advection='MACCORMACK')
    healthy = DenseProjectedSmoke(grid, settings)
    guard = StepCompletion(healthy.device)
    for _ in range(5):  # fixed timestep: the adaptive reductions never run
        healthy.step(1 / 30)
        guard.wait(healthy)
    maxima = dict(guard.maxima)
    assert maxima['density'] > 0 and all(math.isfinite(v) for v in maxima.values()), maxima
    healthy.close()
    cases = [('density', lambda s: s.grid.shape, lambda s, t: setattr(s, '_front', t), float('nan')),
             ('temperature', lambda s: s.grid.shape, lambda s, t: setattr(s, '_temperature', t), float('inf')),
             ('velocity V', lambda s: s.grid.face_shapes[1], lambda s, t: s._velocity.__setitem__(1, t), float('-inf')),
             ('flame', lambda s: s.grid.shape, lambda s, t: setattr(s.combustion, 'flame', t), float('nan')),
             ('velocity W', lambda s: s.grid.face_shapes[2], lambda s, t: s._velocity.__setitem__(2, t), 5e30)]
    detected, legacy_missed = {}, 0
    for name, shape_of, install, value in cases:
        solver = DenseProjectedSmoke(grid, settings)
        guard = StepCompletion(solver.device)
        shape = shape_of(solver)
        install(solver, poisoned_texture(shape, prod(shape) - 1 - 7 * shape[0], value))  # deep inside, not voxel 0
        if name == 'density':  # 0.41's fence sampled voxel (0,0,0) only
            fence = solver.device.kernel('benchmark_fence.glsl', samplers=('densityField', 'temperatureField', 'velocityU',
                                         'velocityV', 'velocityW', 'divergenceField', 'fuelField', 'flameField'))
            pixel = solver.device.texture((1, 1, 1))
            fields = (solver.density, solver.temperature, *solver._velocity, solver.projector.after,
                      solver.combustion.fuel, solver.combustion.flame)
            solver.device.dispatch(fence, pixel, (1, 1, 1), sources=dict(zip(fence_names(), fields)))
            legacy_missed += math.isfinite(solver.device.read(pixel, (1, 1, 1))[0])
        try:
            guard.wait(solver)
            raise AssertionError(f'{name}: invalid value not detected')
        except SimulationFault as exc:
            assert name in str(exc), str(exc)
            detected[name] = str(exc).split(' in ', 1)[1].split('.')[0]
        assert solver.faulted
        try:
            solver.step(1 / 30)
            raise AssertionError('faulted solver kept stepping')
        except RuntimeError as exc:
            assert 'Reset required' in str(exc), str(exc)
        solver.reset()
        assert not solver.faulted
        solver.close()
    assert legacy_missed == 1, 'expected the 0.41 fence to miss an interior NaN'
    return dict(healthy_maxima={k: round(v, 4) for k, v in maxima.items()}, detected=detected,
                legacy_fence_missed_interior_nan=bool(legacy_missed))


def fence_names():
    return ('densityField', 'temperatureField', 'velocityU', 'velocityV', 'velocityW',
            'divergenceField', 'fuelField', 'flameField')


@check
def bake_stops_on_invalid_values(folder):
    import json as _json
    from fluxfx.blender import cache
    scene, _ = fresh_scene(folder / 'nan_bake', end=6)
    scene.fluxfx.adaptive_dt = False
    cache.start_bake(scene)
    job = cache.STATE.job
    while job.frame < 3:
        cache.bake_tick()
    job.solver._front = poisoned_texture(job.solver.grid.shape, 1234, float('nan'))
    while cache.STATE.job is not None:
        cache.bake_tick()
    manifest = _json.loads((job.writer.path / 'manifest.json').read_text())
    assert manifest['status'] == 'FAILED', manifest['status']
    assert 'Invalid simulation values' in manifest['message'], manifest['message']
    assert sorted(manifest['frames'], key=int) == ['1', '2'], manifest['frames']
    scene.fluxfx.adaptive_dt = True
    return dict(status=manifest['status'], frames_kept=sorted(manifest['frames'], key=int),
                message=manifest['message'][:120])


@check
def step_guard_cost(folder):
    import time as _time
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.completion import StepCompletion
    solver = DenseProjectedSmoke(GridSpec((64, 64, 64)), PressureSettings())
    guard = StepCompletion(solver.device)
    fence = solver.device.kernel('benchmark_fence.glsl', samplers=fence_names())
    pixel = solver.device.texture((1, 1, 1))
    fields = (solver.density, solver.temperature, *solver._velocity, solver.projector.after, solver.density, solver.density)
    guard.wait(solver)

    def timed(action, count=20):
        start = _time.perf_counter()
        for _ in range(count):
            action()
        return (_time.perf_counter() - start) / count * 1000
    legacy = timed(lambda: (solver.device.dispatch(fence, pixel, (1, 1, 1), sources=dict(zip(fence_names(), fields))),
                            solver.device.read(pixel, (1, 1, 1))))
    guarded = timed(lambda: guard.wait(solver))
    step = timed(lambda: (solver.step(1 / 30), guard.wait(solver)), 5)
    solver.close()
    import gpu
    renderer = gpu.platform.renderer_get()
    return dict(grid=64, legacy_fence_ms=round(legacy, 3), guard_ms=round(guarded, 3), step_with_guard_ms=round(step, 1),
                guard_added_ms=round(guarded - legacy, 3), renderer=renderer,
                note=('software GPU: absolute times are not Apple GPU times' if 'llvmpipe' in renderer.lower()
                      else 'hardware GPU timing'))


def fire_scene(folder, resolution='32', end=16):
    """The Basic Fire preset's values (the operator itself also starts a live session)."""
    scene, emitter = fresh_scene(folder, resolution=resolution, end=end)
    p = scene.fluxfx
    p.combustion_enabled = p.emission_enabled = True
    p.fuel_source_rate, p.heat_source_rate, p.source_rate = 1, 1000, 0
    p.ignition_temperature, p.burn_rate, p.heat_yield, p.smoke_yield = 150, 4, 600, 1
    p.initial_temperature, p.cooling, p.thermal_lift = 0, .5, .005
    p.vdb_during_bake = p.render_auto_volume = True
    return scene, emitter


def vdb_dense(vdb, path, name, shape):
    import numpy as np
    grid = vdb.read(str(path), name)
    dense = np.zeros(shape, dtype=np.float32)
    grid.copyToArray(dense)
    return grid, dense


def cache_xyz(fields, channel, shape):
    import numpy as np
    flat = np.frombuffer(fields[channel], dtype=np.float32)
    return flat.reshape(shape[2], shape[1], shape[0]).transpose(2, 1, 0)


def compare_export(folder, cache_path, frames=None):
    """Exported grids equal their cached fields (temperature = heat + ambient); all frames by default."""
    import numpy as np
    from fluxfx.blender import render_export
    from fluxfx.physics.cache import CacheReader
    from fluxfx.physics.volume_export import read_manifest
    vdb = render_export.openvdb()
    manifest = read_manifest(folder)
    reader = CacheReader(cache_path)
    shape = tuple(reader.grid.shape)
    worst = 0.0
    for frame, record in manifest['frames'].items():
        if frames is not None and int(frame) not in frames:
            continue
        fields = reader.read(int(frame))
        for plan in manifest['grids']:
            grid, dense = vdb_dense(vdb, Path(folder) / record['file'], plan['name'], shape)
            expected = cache_xyz(fields, plan['channel'], shape) + np.float32(plan['offset'])
            if plan['minimum'] is not None:
                expected = np.maximum(expected, np.float32(plan['minimum']))
            worst = max(worst, float(np.abs(dense - expected).max()))
            assert grid.transform.indexToWorld((0, 0, 0)) == tuple(0.5 / n - 0.5 for n in shape), plan['name']
    assert worst == 0.0, f'exported grids differ from the cache by {worst}'
    return manifest


@check
def fire_bake_writes_matching_vdb_sequence(folder):
    import bpy
    from fluxfx.blender import cache, render_export
    scene, _ = fire_scene(folder / 'fire')
    bake(scene)
    cache_path = Path(scene.fluxfx.cache_path)
    manifest = compare_export(cache_path / 'vdb', cache_path)
    assert manifest['status'] == 'COMPLETE' and len(manifest['frames']) == 16, manifest['status']
    flame_max = manifest['ranges']['flame']['max']
    assert flame_max > 0, 'fire never ignited'
    obj = render_export.render_object(scene)
    assert obj is not None and obj.parent == scene.fluxfx.domain_object, 'render volume missing or unparented'
    volume = obj.data
    assert (volume.is_sequence, volume.frame_start, volume.frame_duration) == (True, 1, 16)
    files = {}
    for frame in (1, 9, 16, 17):
        scene.frame_set(frame)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
        files[frame] = Path(evaluated.grids.frame_filepath).name if evaluated.grids.frame_filepath else None
    assert files == {1: 'fluxfx_00001.vdb', 9: 'fluxfx_00009.vdb', 16: 'fluxfx_00016.vdb', 17: None}, files
    scene.frame_set(16)
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    names = sorted(g.name for g in evaluated.grids) if evaluated.grids.load() else []
    assert names == ['density', 'flame', 'fuel', 'heat', 'temperature'], names
    tree = volume.materials[0].node_tree
    glow, kelvin = tree.nodes[render_export.NODES['glow']], tree.nodes[render_export.NODES['kelvin']]
    assert glow.inputs[1].default_value == scene.fluxfx.render_fire_intensity
    scene.fluxfx.render_fire_intensity, scene.fluxfx.render_flame_temperature = 7.0, 2400.0
    live = (glow.inputs[1].default_value, kelvin.inputs['To Max'].default_value)
    assert live == (7.0, 2400.0), f'render settings did not apply live: {live}'
    scene.fluxfx.property_unset('render_fire_intensity')
    scene.fluxfx.property_unset('render_flame_temperature')
    render_export.update_material(scene)
    # An artist's own material survives re-baking; FluxFX's comes back once the slot is cleared.
    own = bpy.data.materials.new('Artist volume shader')
    volume.materials[0] = own
    render_export.ensure_render_volume(scene, cache_path / 'vdb')
    assert list(volume.materials) == [own], 'custom render material was replaced'
    volume.materials.clear()
    render_export.ensure_render_volume(scene, cache_path / 'vdb')
    assert volume.materials[0].get('fluxfx_material'), 'FluxFX material not restored'
    sizes = [r['bytes'] for r in manifest['frames'].values()]
    return dict(frames=len(manifest['frames']), grids=[g['name'] for g in manifest['grids']],
                flame_max=round(flame_max, 4), temperature_max_K=round(manifest['ranges']['temperature']['max'], 1),
                vdb_mib=round(sum(sizes) / 2 ** 20, 2), scene_frame_to_file=files, loaded_grids_last_frame=names,
                cache_message=cache.STATE.message)


@check
def export_from_existing_cache_matches(folder):
    from fluxfx.blender import render_export
    scene, _ = fire_scene(folder / 'export', end=10)
    scene.fluxfx.vdb_during_bake = False
    scene.fluxfx.cache_compress = True  # also exercises the compressed reader
    bake(scene)
    cache_path = Path(scene.fluxfx.cache_path)
    assert not (cache_path / 'vdb').exists()
    render_export.start_export(scene)
    ticks_used = 0
    while render_export.STATE.job is not None:
        render_export.export_tick()
        ticks_used += 1
    assert render_export.STATE.message.startswith('VDB export complete'), render_export.STATE.message
    manifest = compare_export(cache_path / 'vdb', cache_path)
    scene.fluxfx.cache_compress = False
    return dict(frames=len(manifest['frames']), export_ticks=ticks_used, message=render_export.STATE.message)


def render_setup(scene):
    import bpy
    from math import radians
    camera = bpy.data.objects.new('FluxFX Test Camera', bpy.data.cameras.new('FluxFX Test Camera'))
    scene.collection.objects.link(camera)
    camera.location, camera.rotation_euler = (0, -2.9, 0.55), (radians(90), 0, 0)
    scene.camera = camera
    sun = bpy.data.objects.new('FluxFX Test Sun', bpy.data.lights.new('FluxFX Test Sun', 'SUN'))
    sun.data.energy = 2.5
    sun.rotation_euler = (radians(50), radians(10), radians(30))
    scene.collection.objects.link(sun)
    world = scene.world or bpy.data.worlds.new('FluxFX Test World')
    scene.world = world
    if world.node_tree is None or 'Background' not in world.node_tree.nodes:
        world = scene.world = bpy.data.worlds.new('FluxFX Test World')
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.02, 0.02, 0.025, 1)
    scene.view_settings.view_transform = 'Standard'


def render(scene, path, engine='CYCLES', size=96, samples=16):
    import bpy
    import numpy as np
    scene.render.engine = engine
    if engine == 'CYCLES':
        scene.cycles.device, scene.cycles.samples = 'CPU', samples
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape(size, size, 4)[..., :3]
    bpy.data.images.remove(image)
    return pixels


def fire_pixels(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return int(((r > 0.2) & (r > 1.15 * g) & (g >= b)).sum())


@check
def render_volume_cycles_smoke_and_fire(folder):
    import numpy as np
    from fluxfx.blender import render_export
    scene, _ = fire_scene(folder / 'render', end=24)
    bake(scene)
    obj = render_export.render_object(scene)
    render_setup(scene)
    scene.frame_set(24)
    shots = folder / 'shots'
    shots.mkdir(exist_ok=True)
    results = {}
    for mode in ('FLAME', 'TEMPERATURE', 'NONE'):
        scene.fluxfx.render_fire_mode = mode
        render_export.update_material(scene)
        rgb = render(scene, shots / f'cycles_{mode.lower()}.png')
        results[mode] = dict(fire_pixels=fire_pixels(rgb), mean=round(float(rgb.mean()), 4), rgb=rgb)
    obj.hide_render = True
    empty = render(scene, shots / 'cycles_hidden.png')
    obj.hide_render = False
    smoke_only = render(scene, shots / 'cycles_none_again.png')
    smoke = np.abs(smoke_only - empty).max(axis=2)
    smoke_pixels = int((smoke > 0.01).sum())
    hot = results['TEMPERATURE'].pop('rgb')
    hot_red = float((hot - smoke_only)[..., 0].max())
    # Ambient (293 K) air must stay dark: Cycles' blackbody colour is a constant
    # deep red below 800 K, so ungated emission lit the whole domain box.
    hot_pixels = int((np.abs(hot - empty).max(axis=2) > 0.01).sum())
    for entry in results.values():
        entry.pop('rgb', None)
    details = dict(modes=results, smoke_pixels=smoke_pixels, smoke_max_diff=round(float(smoke.max()), 4),
                   temperature_mode_red_gain=round(hot_red, 4), temperature_mode_lit_pixels=hot_pixels,
                   images=str(shots))
    assert results['FLAME']['fire_pixels'] > 0, f'no blackbody fire in Flame mode: {details}'
    assert results['NONE']['fire_pixels'] == 0, f'emission without fire mode: {details}'
    assert smoke_pixels >= 20, f'smoke not visible: {details}'
    assert hot_red > 0.05, f'no blackbody glow in Temperature mode: {details}'
    assert hot_pixels <= 4 * smoke_pixels, f'ambient air glows in Temperature mode: {details}'
    return details


@check
def render_volume_eevee(folder):
    from fluxfx.blender import render_export
    scene, _ = fire_scene(folder / 'eevee', end=24)
    bake(scene)
    render_setup(scene)
    scene.frame_set(24)
    scene.fluxfx.render_fire_mode = 'FLAME'
    render_export.update_material(scene)
    try:
        rgb = render(scene, folder / 'eevee_flame.png', engine='BLENDER_EEVEE')
    except Exception as exc:  # e.g. no EEVEE-capable GPU context
        return dict(status='UNAVAILABLE', reason=f'{type(exc).__name__}: {exc}')
    pixels = fire_pixels(rgb)
    assert pixels > 0, 'EEVEE rendered no blackbody fire'
    return dict(status='RENDERED', fire_pixels=pixels, mean=round(float(rgb.mean()), 4))


@check(slow=True)
def exit_criteria_128_fire_120_frames(folder):
    """0.42 exit criteria in one run: bake, VDB sequence, exactness, Cycles flame, copy share."""
    from fluxfx.blender import cache, render_export
    from fluxfx.physics import cache as cache_format, volume_export
    timers = dict(readback=Timer(cache, 'capture_views'), cache_write=Timer(cache_format.CacheWriter, 'write'),
                  vdb_write=Timer(volume_export.VDBSequenceWriter, 'write'))
    scene, _ = fire_scene(folder / 'exit128', resolution='128', end=120)
    try:
        started = time.perf_counter()
        bake(scene)
        bake_seconds = time.perf_counter() - started
    finally:
        for timer in timers.values():
            timer.restore()
    cache_path = Path(scene.fluxfx.cache_path)
    manifest = compare_export(cache_path / 'vdb', cache_path, frames={1, 60, 120})
    assert manifest['status'] == 'COMPLETE' and len(manifest['frames']) == 120, manifest['status']
    obj = render_export.render_object(scene)
    assert (obj.data.frame_start, obj.data.frame_duration) == (1, 120)
    render_setup(scene)
    scene.camera.location = (0, -2.2, 0.55)
    renders = {}
    for frame in (40, 80, 120):
        scene.frame_set(frame)
        rgb = render(scene, folder / 'exit128' / f'cycles_{frame}.png', size=320, samples=32)
        renders[frame] = fire_pixels(rgb)
    assert all(renders.values()), f'no visible flame in some frames: {renders}'
    frame_ms = 1000 * bake_seconds / 120
    readback, cache_write = timers['readback'].median_ms(), timers['cache_write'].median_ms()
    return dict(grid=scene.fluxfx.resolution, frames=120, bake_seconds=round(bake_seconds, 1),
                frame_ms_mean=round(frame_ms, 1),
                readback_ms_median=readback, cache_write_ms_median=cache_write,
                vdb_write_ms_median=timers['vdb_write'].median_ms(),
                readback_share=round(readback / frame_ms, 4),
                readback_and_cache_write_share=round((readback + cache_write) / frame_ms, 4),
                vdb_gib=round(sum(r['bytes'] for r in manifest['frames'].values()) / 2 ** 30, 3),
                flame_max=round(manifest['ranges']['flame']['max'], 4),
                cycles_fire_pixels=renders, images=str(folder / 'exit128'))


def main(argv, in_session=False):
    import contextlib
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('-k', dest='only', help='run checks whose name contains this text')
    parser.add_argument('--workdir', type=Path, help='keep bakes, VDB files and renders here (default: a temporary folder)')
    parser.add_argument('--full', action='store_true', help='also run the slow exit-criteria check')
    args = parser.parse_args(argv)
    report = dict(environment=setup_blender(in_session), checks={}, status='PASS')
    report['environment']['mode'] = 'in-session' if in_session else 'fresh process'
    sandbox = SessionSandbox() if in_session else contextlib.nullcontext()
    try:
        with tempfile.TemporaryDirectory() as temp, sandbox:
            run_checks(args, temp, report)
    finally:
        if in_session:
            teardown_blender()
            report['environment']['cleanup'] = f'{getattr(sandbox, "removed", 0)} temporary data-blocks removed; FluxFX unregistered'
    print(json.dumps(report['environment']))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, default=str))
    print('Headless validation:', report['status'])
    return report


def run_in_session(*argv):
    """Entry point for a running graphical Blender (see the module docstring)."""
    return main(list(argv), in_session=True)


def run_checks(args, temp, report):
    if args.workdir:
        args.workdir.mkdir(parents=True, exist_ok=True)
        temp = args.workdir.resolve()
    for function in CHECKS:
        if args.only and args.only not in function.__name__:
            continue
        if function.__name__ in SLOW and not (args.full or args.only):
            continue
        start = time.perf_counter()
        try:
            result = dict(status='PASS', details=function(Path(temp)))
        except Exception as exc:
            result = dict(status='FAIL', error=f'{type(exc).__name__}: {exc}', trace=traceback.format_exc())
            report['status'] = 'FAIL'
        result['seconds'] = round(time.perf_counter() - start, 2)
        report['checks'][function.__name__] = result
        print(f"{result['status']:4} {function.__name__} ({result['seconds']}s)"
              + (f": {result.get('error')}" if result['status'] == 'FAIL' else ''), flush=True)


if __name__ == '__main__':
    # Works as `python3.13 headless_validate.py ...` (bpy module) and as
    # `blender --background --python headless_validate.py -- ...` (real build).
    arguments = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    sys.exit(0 if main(arguments)['status'] == 'PASS' else 1)
