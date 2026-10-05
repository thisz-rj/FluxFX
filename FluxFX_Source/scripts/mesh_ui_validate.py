"""Mesh selection, evaluated geometry changes, modifiers and reset rules."""
from pathlib import Path
import bpy,json,traceback
from fluxfx.blender import runtime
from fluxfx.blender.collider import collider_snapshot
ROOT=Path(__file__).resolve().parents[1]

def run_suite(gpu_test=True):
    report={'status':'RUNNING','tests':[]};old=bpy.context.window.scene
    scene=bpy.data.scenes.new('FluxFX Mesh UI Test');bpy.context.window.scene=scene
    scene.fluxfx.resolution='32';scene.fluxfx.show_preview=False
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    try:
        bpy.ops.mesh.primitive_cube_add(size=.3,location=(0,0,.5));obj=bpy.context.object
        check('selected_mesh_operator',bpy.ops.fluxfx.add_mesh_collider()=={'FINISHED'})
        bpy.context.view_layer.update()
        p=scene.fluxfx;first=collider_snapshot(scene)
        check('assigned_mesh_entry',p.colliders[0].shape=='MESH' and p.colliders[0].collider_object is obj)
        if gpu_test:
            runtime.initialize(scene);s=runtime.STATE.solver
            check('reset_builds_mesh_sdf',s.solids.mesh_sdf is not None and len(s.solids.mesh_reports)==1)
            p.preview_channel='COLLISION'
            check('collision_preview_selection',s.preview_field(p.preview_channel) is s.solids.mask)
            runtime.step(scene)
        obj.location.x+=.05;bpy.context.view_layer.update()
        check('transform_changes_snapshot',collider_snapshot(scene)!=first)
        if gpu_test:
            try:runtime.step(scene);rejected=False
            except ValueError as exc:rejected='Reset' in str(exc)
            check('mesh_motion_requires_reset',rejected)
            runtime.initialize(scene)
        before=collider_snapshot(scene);obj.data.vertices[0].co.x-=.02;obj.data.update();bpy.context.view_layer.update()
        check('vertex_edit_changes_snapshot',collider_snapshot(scene)!=before)
        if gpu_test:
            try:runtime.ensure_current(scene);rejected=False
            except ValueError:rejected=True
            check('geometry_edit_requires_reset',rejected)
        bevel=obj.modifiers.new('FluxFX Test Bevel','BEVEL');bevel.width=.02;bevel.segments=2;bpy.context.view_layer.update()
        check('evaluated_modifiers_included',len(collider_snapshot(scene)[0].triangles)>12)
        p.moving_colliders=True
        try:collider_snapshot(scene);rejected=False
        except ValueError as exc:rejected='static' in str(exc)
        check('moving_mode_rejected',rejected);p.moving_colliders=False
        # Scene links and new enum survive an actual save/load in a separate process.
        p.colliders[0].enabled=False
        check('disabled_mesh_not_in_snapshot',collider_snapshot(scene)==())
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        runtime.shutdown();objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:
            data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if data and data.users==0:bpy.data.meshes.remove(data)
        name='mesh-ui-validation' if gpu_test else 'mesh-scene-cpu-validation'
        (ROOT/'test-results'/f'{name}.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_MESH_UI',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
