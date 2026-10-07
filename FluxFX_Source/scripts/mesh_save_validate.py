"""Background Blender persistence check for mesh collider links and modifiers."""
from pathlib import Path
import sys,json,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import bpy,fluxfx
from fluxfx.blender.collider import collider_snapshot
fluxfx.register()
bpy.ops.mesh.primitive_cube_add(size=.3,location=(0,0,.5))
obj=bpy.context.object;obj.modifiers.new('Bevel','BEVEL').width=.02
bpy.ops.fluxfx.add_mesh_collider();bpy.context.view_layer.update()
bpy.context.scene.fluxfx.preview_channel='COLLISION'
snapshot=collider_snapshot(bpy.context.scene);name=obj.name
with tempfile.TemporaryDirectory() as temp:
    path=str(Path(temp)/'mesh.blend');bpy.ops.wm.save_as_mainfile(filepath=path);bpy.ops.wm.open_mainfile(filepath=path)
    p=bpy.context.scene.fluxfx
    assert p.colliders[0].shape=='MESH' and p.colliders[0].collider_object.name==name
    assert p.preview_channel=='COLLISION'
    assert collider_snapshot(bpy.context.scene)==snapshot
report={'status':'PASS','tests':[{'name':n,'status':'PASS'} for n in ('mesh_link_and_shape','collision_preview_channel','evaluated_geometry_after_load')]}
(ROOT/'test-results/mesh-save-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_MESH_SAVE',report)
fluxfx.unregister()
