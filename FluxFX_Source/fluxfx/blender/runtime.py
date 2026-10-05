"""One ephemeral preview session. All callbacks execute on Blender's main thread."""
from dataclasses import replace
import time
import traceback
import bpy
from bpy.app.handlers import persistent

from ..backend.projected import DenseProjectedSmoke
from ..backend.diagnostics import collect
from ..physics.config import GridSpec
from ..physics.pressure import PressureSettings
from ..physics.interaction import reset_signature
from .collider import collider_snapshot, collider_bindings
from ..physics.collider_motion import MotionPath, validate_motion
from .preview import SlicePreview
from .scene_preview import ScenePreview
from .emitter import source_geometry, emission_snapshot, prepare_emission, prepare_additional_sources
from ..physics.emission import Source
from ..backend.timestep import AdaptiveTimestep
from ..backend.completion import StepCompletion
from ..physics.playback import PlaybackClock, source_span


class Runtime:
    solver = None
    preview = None
    volume_preview = None
    scene_preview = None
    handler = None
    scene = None
    running = False
    error = ""
    submit_ms = 0.0
    signature = None
    projection_report = None
    timestep_controller = None
    timestep_report = None
    emission_history = None
    additional_history = None
    playback = None
    playback_report = None
    completion = None
    collider_signature = ()
    collider_bindings = ()
    collider_motion_report = None


STATE = Runtime()


def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def settings_from_scene(scene):
    props = scene.fluxfx
    n = int(props.resolution)
    center, radius = source_geometry(scene)
    return GridSpec((n, n, n)), PressureSettings(
        turbulence_strength=props.turbulence_strength,turbulence_scale=props.turbulence_scale,
        turbulence_speed=props.turbulence_speed,turbulence_seed=props.turbulence_seed,
        turbulence_octaves=props.turbulence_octaves,turbulence_limit=props.turbulence_limit,
        turbulence_mask=props.turbulence_mask,turbulence_threshold=props.turbulence_threshold,
        combustion_enabled=props.combustion_enabled,
        fuel_source_rate=props.fuel_source_rate if props.emission_enabled else 0.,
        ignition_temperature=props.ignition_temperature,burn_rate=props.burn_rate,
        heat_yield=props.heat_yield,smoke_yield=props.smoke_yield,
        moving_colliders=props.moving_colliders,
        velocity=(0.0, 0.0, props.rise_speed), angular_speed=props.swirl,
        source_center=center, source_radius=radius,density_mode=props.density_mode,source_profile=props.source_profile,
        source_rate=props.source_rate if props.emission_enabled else 0.0, dissipation=props.dissipation,
        initial_temperature=props.initial_temperature, heat_source_rate=props.heat_source_rate if props.emission_enabled else 0.0,
        cooling=props.cooling, thermal_lift=props.thermal_lift, density_weight=props.density_weight,
        pressure_iterations=props.pressure_iterations, pressure_solver=props.pressure_solver,
        pressure_cycles=props.pressure_cycles,velocity_advection=props.velocity_advection,scalar_advection=props.scalar_advection,
        vorticity_strength=props.vorticity_strength,vorticity_limit=props.vorticity_limit)


def pause():
    STATE.running = False
    STATE.playback = None
    STATE.emission_history = None
    STATE.additional_history = None
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    redraw()


def shutdown():
    from . import native_runtime, regions
    regions.shutdown()
    native_runtime.shutdown()
    from . import cache, render_export
    cache.shutdown()
    render_export.shutdown()
    pause()
    if STATE.handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(STATE.handler, "WINDOW")
    STATE.handler = None
    STATE.preview = None
    STATE.volume_preview = None
    STATE.scene_preview = None
    if STATE.timestep_controller is not None:
        STATE.timestep_controller.close()
    STATE.timestep_controller = None
    STATE.timestep_report = None
    if STATE.completion is not None:
        STATE.completion.close()
    STATE.completion = None
    STATE.playback_report = None
    if STATE.solver is not None:
        STATE.solver.close()
    STATE.solver = None
    STATE.scene = None
    STATE.signature = None
    STATE.collider_signature = ()
    STATE.collider_bindings = ()
    STATE.collider_motion_report = None
    STATE.projection_report = None
    STATE.error = ""
    STATE.submit_ms = 0.0


def initialize(scene):
    shutdown()
    report = collect(run_probe=True)
    if report["status"] != "READY":
        raise RuntimeError(f"GPU validation failed: {report}")
    try:
        grid, settings = settings_from_scene(scene)
        STATE.collider_signature = collider_snapshot(scene)
        STATE.collider_bindings = collider_bindings(scene)
        STATE.solver = DenseProjectedSmoke(grid, settings, colliders=STATE.collider_signature)
        STATE.timestep_controller = AdaptiveTimestep(grid, STATE.solver.device)
        STATE.completion = StepCompletion(STATE.solver.device)
        STATE.preview = SlicePreview()
        STATE.volume_preview = SlicePreview(volume=True)
        STATE.scene_preview = ScenePreview()
        STATE.scene = scene
        STATE.signature = (grid, settings)
        _, STATE.additional_history = prepare_additional_sources(scene,None)
        STATE.emission_history = emission_snapshot(scene)
        STATE.handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
    except Exception:
        shutdown()
        raise
    redraw()


def ensure_current(scene):
    if STATE.solver is not None and STATE.scene == scene:
        current=collider_snapshot(scene)
        if STATE.solver.settings.moving_colliders:
            if collider_bindings(scene)!=STATE.collider_bindings:
                raise ValueError('Collider entries changed; press Reset')
            validate_motion(STATE.collider_signature,current)
        elif current!=STATE.collider_signature:
            raise ValueError("Static colliders changed; press Reset to rebuild the solid grid")
    grid, settings = settings_from_scene(scene)
    if (STATE.solver is None or STATE.scene != scene or STATE.signature[0] != grid
            or reset_signature(STATE.signature[1]) != reset_signature(settings)):
        initialize(scene)
    elif STATE.signature[1] != settings:
        STATE.solver.update_settings(settings)
        STATE.signature = (grid, settings)


def step(scene):
    ensure_current(scene)
    start = time.perf_counter()
    STATE.projection_report = None
    STATE.timestep_report = None
    props = scene.fluxfx
    emission, snapshot = prepare_emission(scene, STATE.emission_history)
    additional, additional_snapshots = prepare_additional_sources(scene,STATE.additional_history)
    settings=STATE.solver.settings
    sources=([Source(settings.source_center,settings.source_radius,settings.source_rate,
                     settings.heat_source_rate,emission,settings.density_mode,settings.source_profile,settings.fuel_source_rate)]+additional) if additional else None
    if props.adaptive_dt:
        report = STATE.timestep_controller.select(STATE.solver, props.time_step, props.cfl_target, emission, sources)
    else:
        report = {"mode": "FIXED", "dt": props.time_step}
    if settings.moving_colliders and STATE.solver.solids is not None:
        path=MotionPath(STATE.solver.solids.colliders,collider_snapshot(scene),props.time_step)
        report['dt']=path.limit_dt(report['dt'],STATE.solver.grid.cell_size)
        STATE.solver.move_colliders(path.at(report['dt']),report['dt'])
        STATE.collider_motion_report={'remaining_metres':max(0.,path.distance-path.speed*report['dt'])}
    STATE.solver.step(report["dt"], emission, sources)
    STATE.completion.wait(STATE.solver)
    STATE.additional_history = additional_snapshots
    STATE.emission_history = snapshot
    STATE.timestep_report = report
    STATE.submit_ms = (time.perf_counter() - start) * 1000.0
    redraw()


def measure_projection(scene):
    pause()
    ensure_current(scene)
    STATE.projection_report = STATE.solver.measure_projection()
    redraw()
    return STATE.projection_report


def start(scene):
    if STATE.running and STATE.scene == scene:
        return
    ensure_current(scene)
    _, STATE.additional_history = prepare_additional_sources(scene,None)
    STATE.emission_history = emission_snapshot(scene)
    STATE.playback = PlaybackClock(time.perf_counter())
    STATE.playback_report = None
    STATE.running = True
    STATE.error = ""
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=1.0 / 30.0)


def tick():
    started = time.perf_counter()
    if not STATE.running:
        return None
    try:
        if STATE.scene != bpy.context.scene:
            STATE.running = False
            STATE.playback = None
            redraw()
            return None
        grid, settings = settings_from_scene(STATE.scene)
        if (STATE.signature[0] != grid
                or reset_signature(STATE.signature[1]) != reset_signature(settings)):
            # Property edits need an explicit reset. Never restart inside a live timer.
            STATE.running = False
            STATE.playback = None
            STATE.error = "Settings changed; press Reset to rebuild the preview."
            redraw()
            return None
        ensure_current(STATE.scene)
        playback = STATE.playback
        dropped = playback.begin(time.perf_counter())
        if dropped:
            # A stalled UI/sleep is not a recorded animation: discard stale trails.
            STATE.emission_history = None
            STATE.additional_history = None
        duration = max(playback.debt, 1e-6)
        scene = STATE.scene
        props = scene.fluxfx
        emission, snapshot = prepare_emission(scene, STATE.emission_history, interval=duration)
        additional, snapshots = prepare_additional_sources(scene, STATE.additional_history, interval=duration)
        settings = STATE.solver.settings
        sampled = [Source(settings.source_center, settings.source_radius, settings.source_rate,
                          settings.heat_source_rate, emission, settings.density_mode, settings.source_profile, settings.fuel_source_rate)] + additional
        motion_path=(MotionPath(STATE.solver.solids.colliders,collider_snapshot(scene),duration)
                     if settings.moving_colliders and STATE.solver.solids is not None else None)
        consumed = 0.0

        def advance(remaining):
            nonlocal consumed
            started = time.perf_counter()
            maximum = min(props.time_step, remaining)
            report = (STATE.timestep_controller.select(STATE.solver, maximum, props.cfl_target,
                                                       emission, sampled) if props.adaptive_dt
                      else {"mode": "FIXED", "dt": maximum})
            dt = report["dt"]
            if motion_path is not None:
                dt=report['dt']=motion_path.limit_dt(dt,grid.cell_size)
                STATE.solver.move_colliders(motion_path.at(consumed+dt),dt)
                STATE.collider_motion_report={'remaining_metres':max(0.,motion_path.distance-motion_path.speed*(consumed+dt))}
            begin = min(1.0, consumed / duration)
            end = min(1.0, (consumed + dt) / duration)
            sources = [source_span(source, begin, end) for source in sampled]
            # Preserve the faster single-source path without modifying saved UI properties.
            if additional:
                STATE.solver.step(dt, sources=sources)
            else:
                STATE.solver.update_settings(replace(settings, source_center=sources[0].center))
                try:
                    STATE.solver.step(dt, sources[0].motion)
                finally:
                    STATE.solver.update_settings(settings)
            STATE.completion.wait(STATE.solver)
            consumed += dt
            STATE.emission_history = (sources[0].center, *snapshot[1:])
            STATE.additional_history = {key: (source.center, *value[1:])
                                        for (key, value), source in zip(snapshots.items(), sources[1:])}
            STATE.timestep_report = report
            STATE.projection_report = None
            STATE.submit_ms = (time.perf_counter() - started) * 1000
            return dt

        interval = playback.run(advance, props.playback_budget_ms / 1000, time.perf_counter, started=started)
        STATE.playback_report = playback.report
        redraw()
    except Exception as exc:
        STATE.running = False
        STATE.playback = None
        STATE.error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        redraw()
        return None
    return interval


def draw():
    if STATE.solver is None or STATE.scene != bpy.context.scene:
        return
    if STATE.solver.faulted:  # never raymarch NaN/Inf or half-written fields
        return
    props = STATE.scene.fluxfx
    if not props.show_preview or STATE.preview is None:
        return
    if props.preview_channel=="COLLISION" and STATE.solver.solids is None:
        return
    if props.preview_channel in {"FUEL","FLAME"} and STATE.solver.combustion is None:
        return
    try:
        if props.preview_mode == "SCENE":
            STATE.scene_preview.draw(STATE.solver, STATE.scene)
            return
        preview = STATE.volume_preview if props.preview_mode == "VOLUME" else STATE.preview
        preview.draw(STATE.solver, props.slice_y, props.exposure, props.preview_channel, int(props.ray_steps))
    except Exception as exc:
        STATE.error = f"Preview: {exc}"
        STATE.preview = None  # prevent an exception storm on redraw
        pause()
        traceback.print_exc()


@persistent
def before_load(_):
    shutdown()


@persistent
def before_undo(_):
    shutdown()
