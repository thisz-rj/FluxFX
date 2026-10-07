"""Temporary-scene object bindings, reset rules and live timer stop checks."""
from pathlib import Path
import json, traceback
import bpy
from fluxfx.blender import runtime
from fluxfx.blender.collider import create_collider, collider_snapshot
ROOT=Path(__file__).resolve().parents[1]


def run():
    report={'status':'RUNNING','tests':[]}
    old=bpy.context.window.scene
    scene=bpy.data.scenes.new('FluxFX Collider Test')
    bpy.context.window.scene=scene
    scene.fluxfx.resolution='32'
    scene.fluxfx.show_preview=False
    def check(name, condition):
        assert condition,name
        report['tests'].append({'name':name,'status':'PASS'})
    def finish():
        runtime.shutdown()
        objects=list(scene.objects)
        bpy.context.window.scene=old
        bpy.data.scenes.remove(scene)
        for obj in objects:
            if obj.users==0:bpy.data.objects.remove(obj)
        (ROOT/'test-results/collider-ui-validation.json').write_text(json.dumps(report,indent=2)+'\n')
        print('FLUXFX_COLLIDER_UI',report['status'],report.get('traceback',''))
    try:
        sphere=create_collider(scene,'SPHERE');box=create_collider(scene,'BOX')
        sphere.location=(.1,0,0);box.location=(-.2,0,.1);box.rotation_euler.z=.4
        bpy.context.view_layer.update()
        scene.fluxfx.colliders[0].shape='BOX'
        check('owned_display_tracks_shape',sphere.empty_display_type=='CUBE')
        scene.fluxfx.colliders[0].shape='SPHERE'
        snapshot=collider_snapshot(scene)
        check('object_bindings_shapes',len(snapshot)==2 and snapshot[0].shape=='SPHERE' and snapshot[1].shape=='BOX')
        check('object_transform_coordinates',snapshot[0].contains((.6,.5,.5)) and not snapshot[0].contains((.1,.5,.5)))
        domain=scene.fluxfx.domain_object
        domain.location.x=2
        bpy.context.view_layer.update()
        moved=collider_snapshot(scene)
        check('domain_parenting_preserves_local_geometry',all(abs(a-b)<1e-5 for ca,cb in zip(snapshot,moved) for ra,rb in zip(ca.inverse_rows,cb.inverse_rows) for a,b in zip(ra,rb)))
        runtime.initialize(scene);runtime.step(scene)
        solver=runtime.STATE.solver
        check('runtime_selects_masked_pressure',solver.solids is not None and solver.projector.uses_impulse)
        sphere.location.x+=.1;bpy.context.view_layer.update()
        try:runtime.step(scene);raised=False
        except ValueError:raised=True
        check('paused_edit_requires_explicit_reset',raised and runtime.STATE.solver is solver)
        runtime.initialize(scene)
        check('reset_rebuilds_and_releases_mask',runtime.STATE.solver is not solver and solver.solids is None)
        scene.fluxfx.colliders[1].enabled=False
        scene.fluxfx.colliders[1].collider_object=None
        check('disabled_missing_object_ignored',len(collider_snapshot(scene))==1)
        scene.fluxfx.colliders[1].enabled=True
        try:collider_snapshot(scene);raised=False
        except ValueError:raised=True
        check('enabled_missing_object_rejected',raised)
        scene.fluxfx.colliders[1].collider_object=box
        box.scale=(0,0,0);bpy.context.view_layer.update()
        try:collider_snapshot(scene);raised=False
        except ValueError:raised=True
        check('singular_object_rejected',raised)
        box.scale=(.18,.18,.12);bpy.context.view_layer.update()
        runtime.initialize(scene);runtime.start(scene)
        def move():
            sphere.location.z+=.1;bpy.context.view_layer.update()
            return None
        def done():
            try:
                check('timer_advanced_before_edit',runtime.STATE.solver.steps>0)
                check('live_collider_edit_stops_timer',not runtime.STATE.running and not bpy.app.timers.is_registered(runtime.tick)
                    and runtime.STATE.playback is None and 'Reset' in runtime.STATE.error)
                runtime.before_undo(None)
                check('undo_releases_collision_session',runtime.STATE.solver is None and runtime.STATE.collider_signature==())
                report['status']='PASS'
            except Exception:
                report['status']='FAIL';report['traceback']=traceback.format_exc()
            finish();return None
        bpy.app.timers.register(move,first_interval=.25)
        bpy.app.timers.register(done,first_interval=.7)
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc();finish()

if __name__=='__main__':run()
