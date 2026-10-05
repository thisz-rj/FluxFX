"""Graphical Blender: actual timers, moving objects, live edits and overload.
Runs in temporary scenes and restores the original scene without saving it.
"""
import json
import math
from pathlib import Path
import runpy
import time
import traceback
import bpy

ROOT = Path(__file__).resolve().parents[1]


def run():
    runpy.run_path(str(ROOT / 'scripts/dev_load.py'), run_name='fluxfx_dev_load')
    from fluxfx.blender import runtime
    from fluxfx.blender.emitter import create_emitter, create_additional_emitter
    output = ROOT / 'test-results/playback-validation.json'
    output.parent.mkdir(exist_ok=True)
    report = {'status': 'RUNNING', 'blender': bpy.app.version_string, 'cases': [], 'tests': []}
    original_scene = bpy.context.window.scene
    area = bpy.context.area
    original_type = area.type
    area.type = 'VIEW_3D'
    state = {'index': 0, 'scene': None}
    cases = [('stationary', '64', 24), ('moving', '64', 24), ('multiple', '64', 24), ('overload', '128', 1)]

    def record(name, condition):
        assert condition, name
        report['tests'].append({'name': name, 'status': 'PASS'})

    def cleanup():
        runtime.shutdown()
        bpy.context.window.scene = original_scene
        if state['scene']:
            objects = list(state['scene'].objects)
            bpy.data.scenes.remove(state['scene'])
            for obj in objects:
                if obj.users == 0: bpy.data.objects.remove(obj)
            state['scene'] = None

    def finish():
        cleanup()
        area.type = original_type
        output.write_text(json.dumps(report, indent=2) + '\n')
        print('FLUXFX_PLAYBACK_VALIDATION', report['status'])

    def begin_case():
        name, resolution, budget = cases[state['index']]
        scene = bpy.data.scenes.new('FluxFX Playback Test')
        state['scene'] = scene
        bpy.context.window.scene = scene
        p = scene.fluxfx
        p.resolution = resolution
        p.playback_budget_ms = budget
        p.preview_mode = 'SCENE'
        p.emission_velocity = (0, 0, .5)
        p.motion_inheritance = .2
        p.continuous_trails = True
        obj = create_emitter(scene)
        extra = create_additional_emitter(scene) if name == 'multiple' else None
        bpy.context.view_layer.update()
        runtime.initialize(scene)
        # Compile/complete one step outside the timed session.
        runtime.step(scene)
        runtime.start(scene)
        state.update(name=name, obj=obj, extra=extra, start=time.perf_counter(),
                     initial=runtime.STATE.solver.time, samples=[], centers=[], extra_centers=[], seen=-1,
                     solver=runtime.STATE.solver, edited=False)

    def poll():
        try:
            scene = state['scene']; p = scene.fluxfx
            elapsed = time.perf_counter() - state['start']
            record_once = runtime.STATE.playback_report
            assert not runtime.STATE.error, runtime.STATE.error
            assert runtime.STATE.running, 'Playback stopped unexpectedly'
            if record_once and state['seen'] != runtime.STATE.solver.steps:
                state['samples'].append(dict(record_once))
                state['seen'] = runtime.STATE.solver.steps
                state['centers'].append(runtime.STATE.emission_history[0][0])
                state['extra_centers'].extend(s[0][0] for s in runtime.STATE.additional_history.values())
            if state['name'] in ('moving', 'multiple'):
                state['obj'].location.x = .15 * math.sin(elapsed * 2)
                if state['extra']:
                    state['extra'].location.x = -.2 * math.sin(elapsed * 2)
                bpy.context.view_layer.update()
            if elapsed > 1 and not state['edited']:
                p.source_rate = 1.7
                p.vorticity_strength = .2
                state['edited'] = True
            if elapsed < 4:
                return .01
            samples = state['samples']
            solver = runtime.STATE.solver
            simulated = solver.time - state['initial']
            final = dict(runtime.STATE.playback_report)
            record(state['name'] + '_advanced', simulated > 0 and len(samples) > 2)
            record(state['name'] + '_live_edit_preserves_fields', solver is state['solver'] and abs(solver.settings.source_rate - 1.7) < 1e-5)
            record(state['name'] + '_cfl_safe', runtime.STATE.timestep_report['estimated_courant'] <= p.cfl_target + 1e-6)
            if state['name'] in ('moving', 'multiple'):
                record(state['name'] + '_object_motion_consumed', max(state['centers']) - min(state['centers']) > .2)
            if state['name'] == 'multiple':
                record('additional_object_motion_consumed', max(state['extra_centers']) - min(state['extra_centers']) > .2)
            record(state['name'] + '_wall_time_accounted', abs(runtime.STATE.playback.simulated + runtime.STATE.playback.debt + runtime.STATE.playback.dropped - (runtime.STATE.playback.last - runtime.STATE.playback.epoch)) < 1e-6)
            if state['name'] == 'overload':
                record('overload_yields_after_one_completed_step', all(s['substeps'] == 1 for s in samples))
                record('overload_reports_skipped_time', final['dropped_seconds'] > 0)
            else:
                record(state['name'] + '_multiple_substeps', max(s['substeps'] for s in samples) > 1)
            report['cases'].append(dict(name=state['name'], resolution=int(p.resolution), budget_ms=p.playback_budget_ms,
                wall_seconds=elapsed, simulated_seconds=simulated, speed=simulated/elapsed,
                final=final, observed_callbacks=samples))
            runtime.pause()
            record(state['name'] + '_pause_clears_clock', runtime.STATE.playback is None and not bpy.app.timers.is_registered(runtime.tick))
            runtime.start(scene)
            record(state['name'] + '_resume_has_no_debt', runtime.STATE.playback.debt == 0)
            runtime.pause()
            cleanup()
            record(state['name'] + '_release_completion', runtime.STATE.completion is None and runtime.STATE.playback_report is None)
            state['index'] += 1
            if state['index'] < len(cases):
                begin_case()
                return .01
            report['status'] = 'PASS'
            finish()
        except Exception:
            report['status'] = 'FAIL'
            report['traceback'] = traceback.format_exc()
            finish()
        return None

    try:
        begin_case()
        bpy.app.timers.register(poll, first_interval=.01)
    except Exception:
        report['status'] = 'FAIL'; report['traceback'] = traceback.format_exc(); finish()


if __name__ == '__main__':
    run()
