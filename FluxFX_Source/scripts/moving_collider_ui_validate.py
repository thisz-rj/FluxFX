"""Actual Blender object motion during live simulation, in a temporary scene."""
from pathlib import Path
import json,traceback
import bpy
from fluxfx.blender import runtime
from fluxfx.blender.collider import create_collider
from fluxfx.physics.collider_motion import Pose
ROOT=Path(__file__).resolve().parents[1]


def run():
    report={'status':'RUNNING','tests':[]}
    old=bpy.context.window.scene
    scene=bpy.data.scenes.new('FluxFX Moving Collider Test');bpy.context.window.scene=scene
    props=scene.fluxfx;props.resolution='32';props.show_preview=False;props.moving_colliders=True
    def check(name,condition):
        assert condition,name
        report['tests'].append(dict(name=name,status='PASS'))
    def finish():
        runtime.shutdown();objects=list(scene.objects);bpy.context.window.scene=old
        bpy.data.scenes.remove(scene)
        for obj in objects:
            if obj.users==0:bpy.data.objects.remove(obj)
        (ROOT/'test-results/moving-collider-ui-validation.json').write_text(json.dumps(report,indent=2))
        print('FLUXFX_MOVING_COLLIDER_UI',report['status'],report.get('traceback',''))
    def guarded(fn):
        def run_stage():
            try:fn()
            except Exception:
                report['status']='FAIL';report['traceback']=traceback.format_exc();finish()
            return None
        return run_stage
    try:
        obj=create_collider(scene,'BOX');bpy.context.view_layer.update()
        runtime.initialize(scene);solver=runtime.STATE.solver
        check('moving_mode_uses_gpu_jacobi',solver.projector.__class__.__name__=='SolidPressureProjector')
        initial=Pose.from_collider(solver.solids.colliders[0])
        runtime.start(scene)
        def move():
            obj.location.x+=.06;obj.rotation_euler.z=.3;bpy.context.view_layer.update()
            bpy.app.timers.register(guarded(verify),first_interval=.6)
        def verify():
            check('motion_keeps_live_solver',runtime.STATE.running and runtime.STATE.solver is solver)
            pose=Pose.from_collider(solver.solids.colliders[0])
            check('object_translation_updates_mask_pose',pose.center[0]>initial.center[0]+.02)
            check('object_rotation_updates_mask_pose',abs(pose.orientation[3])>.01)
            check('timer_advances',solver.steps>2)
            runtime.pause();runtime.step(scene)
            check('manual_step_supports_motion',runtime.STATE.solver is solver)
            props.scalar_advection='SEMI_LAGRANGIAN';runtime.step(scene)
            check('transport_setting_live_with_motion',runtime.STATE.solver is solver)
            runtime.start(scene);obj.scale.x*=1.5;bpy.context.view_layer.update()
            bpy.app.timers.register(guarded(reject),first_interval=.25)
        def reject():
            check('resize_stops_with_reset_message',not runtime.STATE.running and 'Reset' in runtime.STATE.error)
            runtime.initialize(scene)
            check('reset_accepts_new_fixed_size',runtime.STATE.solver is not solver and not runtime.STATE.error)
            runtime.before_undo(None)
            check('undo_releases_moving_resources',runtime.STATE.solver is None and runtime.STATE.collider_bindings==())
            report['status']='PASS';finish()
        bpy.app.timers.register(guarded(move),first_interval=.15)
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc();finish()
if __name__=='__main__':run()
