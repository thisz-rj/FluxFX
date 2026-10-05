"""Headless Blender validation: FluxFX's real GPU solver and Blender integration
without a window.

Runs inside Blender-as-a-Python-module (`bpy`) with an EGL GPU context: a
hardware GPU, or Mesa llvmpipe in software on Linux CI. It exercises code the
standalone unit suite cannot reach: GPU baking, cache playback validation,
the invalid-value guard and volume export/rendering.

    pip install bpy==5.2.2 numpy        # Python 3.13; Blender 5.3 when published
    EGL_PLATFORM=surfaceless python3.13 scripts/headless_validate.py --output report.json

or with an installed Blender (Metal on Apple Silicon), without a window:

    blender --background --factory-startup --python scripts/headless_validate.py -- --output report.json

Limits: OpenGL, not Metal; timers and draw handlers never fire without an
event loop, so the harness calls the same functions the timers would. Blender
older than the manifest minimum is registered with the version gate bypassed
and reported as such. Exit status is nonzero if any check fails.
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


def check(function):
    CHECKS.append(function)
    return function


def setup_blender():
    import bpy
    import gpu
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


def fresh_scene(folder, resolution='16', start=1, end=6):
    import bpy
    from fluxfx.blender.domain import create_domain
    from fluxfx.blender.emitter import create_emitter
    from fluxfx.blender import cache, runtime
    runtime.shutdown()
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
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
    return dict(grid=64, legacy_fence_ms=round(legacy, 3), guard_ms=round(guarded, 3), step_with_guard_ms=round(step, 1),
                note='software GPU (llvmpipe): absolute times are not Apple GPU times')


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('-k', dest='only', help='run checks whose name contains this text')
    args = parser.parse_args(argv)
    report = dict(environment=setup_blender(), checks={}, status='PASS')
    with tempfile.TemporaryDirectory() as temp:
        for function in CHECKS:
            if args.only and args.only not in function.__name__:
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
    print(json.dumps(report['environment']))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, default=str))
    print('Headless validation:', report['status'])
    return report


if __name__ == '__main__':
    # Works as `python3.13 headless_validate.py ...` (bpy module) and as
    # `blender --background --python headless_validate.py -- ...` (real build).
    arguments = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    sys.exit(0 if main(arguments)['status'] == 'PASS' else 1)
