"""Development-only UI/lifecycle smoke test in a Blender window.

Run this from the Text Editor with no installed FluxFX copy enabled. It reloads
the source add-on, tests playback asynchronously in a temporary scene, writes a
JSON report, and restores the original scene without saving.
"""
import json
from pathlib import Path
import runpy
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]


def run():
    runpy.run_path(str(ROOT / "scripts/dev_load.py"), run_name="fluxfx_dev_load")
    import fluxfx
    from fluxfx.blender import runtime

    report = {"status": "RUNNING", "tests": []}
    output = ROOT / "test-results/ui-validation.json"
    output.parent.mkdir(exist_ok=True)

    def record(name, condition):
        assert condition, name
        report["tests"].append({"name": name, "status": "PASS"})

    old_scene = bpy.context.window.scene
    scene = bpy.data.scenes.new("FluxFX UI Test")
    bpy.context.window.scene = scene
    scene.fluxfx.source_mode = "MANUAL"
    scene.fluxfx.resolution = "64"
    scene.fluxfx.source_center = (0.5, 0.5, 0.16)
    scene.fluxfx.emission_enabled = True
    runtime.initialize(scene)
    runtime.start(scene)
    original_solver = runtime.STATE.solver

    def edit_live():
        scene.fluxfx.source_center = (0.7, 0.5, 0.16)
        scene.fluxfx.emission_enabled = False
        scene.fluxfx.turbulence_strength = 2
        scene.fluxfx.turbulence_seed = 37
        scene.fluxfx.turbulence_mask = "ALL"
        scene.fluxfx.turbulence_scale = 0.75
        scene.fluxfx.turbulence_speed = 0.8
        scene.fluxfx.turbulence_octaves = 4
        scene.fluxfx.turbulence_limit = 1
        scene.fluxfx.turbulence_threshold = 0.5
        return None

    bpy.app.timers.register(edit_live, first_interval=0.2)

    def finish():
        try:
            record("timer_advances_simulation", runtime.STATE.solver.steps > 0)
            record("preview_compiles", runtime.STATE.preview is not None and runtime.STATE.volume_preview is not None and runtime.STATE.scene_preview is not None)
            record("no_runtime_errors", not runtime.STATE.error)
            record("live_edit_during_playback", runtime.STATE.solver is original_solver
                   and abs(original_solver.settings.source_center[0] - 0.7) < 1e-6
                   and original_solver.settings.source_rate == 0
                   and original_solver.settings.heat_source_rate == 0
                   and runtime.STATE.running)
            record("turbulence_live_controls", original_solver.settings.turbulence_seed == 37
                   and original_solver.settings.turbulence_strength == 2
                   and original_solver.settings.turbulence_scale == 0.75
                   and abs(original_solver.settings.turbulence_speed - 0.8) < 1e-6
                   and original_solver.settings.turbulence_octaves == 4
                   and original_solver.settings.turbulence_limit == 1
                   and original_solver.settings.turbulence_threshold == 0.5
                   and original_solver.settings.turbulence_mask == "ALL"
                   and original_solver.turbulence.allocated_bytes > 0)
            runtime.pause()
            scene.fluxfx.turbulence_strength = 0
            runtime.step(scene)
            record("turbulence_disable_live", runtime.STATE.solver is original_solver
                   and original_solver.settings.turbulence_strength == 0)
            record("pause_removes_timer", not bpy.app.timers.is_registered(runtime.tick))
            runtime.start(scene)
            scene.fluxfx.resolution = "32"
            runtime.tick()
            record("reset_edit_stops_playback_clock", not runtime.STATE.running and runtime.STATE.playback is None)
            runtime.pause()
            scene.fluxfx.resolution = "64"
            runtime.start(scene)
            bpy.context.window.scene = old_scene
            runtime.tick()
            record("scene_change_stops_playback_clock", not runtime.STATE.running and runtime.STATE.playback is None)
            bpy.context.window.scene = scene
            runtime.shutdown()
            record("release_clears_owned_resources", runtime.STATE.solver is None and runtime.STATE.handler is None
                   and runtime.STATE.preview is None and runtime.STATE.volume_preview is None and runtime.STATE.scene_preview is None and runtime.STATE.scene is None
                   and runtime.STATE.timestep_controller is None and runtime.STATE.completion is None
                   and runtime.STATE.playback is None and runtime.STATE.playback_report is None)
            for name, cleanup in (("undo_cleanup", runtime.before_undo), ("file_load_cleanup", runtime.before_load)):
                runtime.initialize(scene)
                runtime.start(scene)
                cleanup(None)
                record(name, runtime.STATE.solver is None and runtime.STATE.handler is None
                       and not bpy.app.timers.is_registered(runtime.tick))
            runtime.initialize(scene)
            runtime.start(scene)
            fluxfx.unregister()
            record("disable_during_playback", runtime.STATE.handler is None and runtime.STATE.solver is None
                   and not bpy.app.timers.is_registered(runtime.tick) and not hasattr(bpy.types.Scene, "fluxfx"))
            fluxfx.register()
            scene.fluxfx.resolution = "128"
            scene.fluxfx.pressure_solver = "AUTO"
            runtime.initialize(scene)
            runtime.step(scene)
            record("auto_128_multigrid", runtime.STATE.solver.projector.__class__.__name__ == "MultigridPressureProjector")
            current = runtime.STATE.solver
            scene.fluxfx.pressure_cycles = 5
            runtime.step(scene)
            record("multigrid_cycles_live", runtime.STATE.solver is current and current.projector.last_cycles == 5)
            scene.fluxfx.pressure_solver = "JACOBI"
            runtime.step(scene)
            record("solver_switch_rebuilds", runtime.STATE.solver is not current
                   and runtime.STATE.solver.projector.__class__.__name__ == "PressureProjector"
                   and runtime.STATE.solver.steps == 1)
            record("multigrid_resources_released", current.projector is None)
            scene.fluxfx.resolution = "64"
            scene.fluxfx.pressure_solver = "AUTO"
            scene.fluxfx.pressure_cycles = 4
            scene.fluxfx.source_center = (0.5, 0.5, 0.16)
            scene.fluxfx.emission_enabled = True
            runtime.initialize(scene)
            for _ in range(60):
                runtime.step(scene)
            record("preview_restored_paused", not runtime.STATE.running and runtime.STATE.solver.steps == 60)
            if hasattr(runtime.STATE.solver, "measure_projection"):
                measurement = runtime.measure_projection(scene)
                record("projection_measurement", measurement["step"] == 60
                       and measurement["ratio"] is not None and measurement["ratio"] < 0.1)
                runtime.step(scene)
                record("measurement_invalidated_after_step", runtime.STATE.projection_report is None)
                runtime.measure_projection(scene)
            record("adaptive_step_report", runtime.STATE.timestep_report["mode"] == "ADAPTIVE"
                   and runtime.STATE.timestep_report["estimated_courant"] <= scene.fluxfx.cfl_target)
            report["status"] = "PASS"
        except Exception:
            report["status"] = "FAIL"
            report["traceback"] = traceback.format_exc()
            runtime.pause()
        runtime.shutdown()
        bpy.context.window.scene = old_scene
        bpy.data.scenes.remove(scene)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print("FLUXFX_UI_VALIDATION", report)
        return None

    bpy.app.timers.register(finish, first_interval=1.0)


if __name__ == "__main__":
    run()
