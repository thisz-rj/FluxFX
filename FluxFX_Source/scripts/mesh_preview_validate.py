"""Render the actual collision mask: concave torus hole must stay transparent."""
from pathlib import Path
import bpy,gpu,json,traceback
from mathutils import Matrix
from fluxfx.blender.scene_preview import ScenePreview
from fluxfx.blender.collider import collider_snapshot
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.physics.config import GridSpec
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Mesh Preview Test');bpy.context.window.scene=scene
    solver=target=None;report={'status':'RUNNING','tests':[]}
    try:
        bpy.ops.mesh.primitive_torus_add(major_segments=32,minor_segments=12,major_radius=.23,minor_radius=.09,location=(0,0,.5))
        bpy.ops.fluxfx.add_mesh_collider();bpy.context.view_layer.update()
        solver=DenseProjectedSmoke(GridSpec((32,)*3),colliders=collider_snapshot(scene))
        target=gpu.types.GPUOffScreen(256,256,format='RGBA32F');renderer=ScenePreview()
        transform=Matrix.Translation((.5,.5,.5))@Matrix.Diagonal((.5,.5,1.,1.))
        with target.bind():
            fb=gpu.state.active_framebuffer_get();fb.clear(color=(0,0,0,0))
            renderer.render(solver.preview_field('COLLISION'),transform,10)
            buffer=fb.read_color(0,0,256,256,4,0,'FLOAT');buffer.dimensions=256*256*4;pixels=list(buffer)
        for name,x,y,visible in (('hole_transparent',128,128,False),('ring_visible',186,128,True),('outside_transparent',10,10,False)):
            alpha=pixels[4*(x+256*y)+3];assert alpha>.5 if visible else alpha<1e-6,(name,alpha)
            report['tests'].append(dict(name=name,status='PASS',alpha=alpha))
        img=bpy.data.images.new('FluxFX collision preview',256,256,alpha=True,float_buffer=True)
        try:
            img.pixels.foreach_set([v if i%4!=3 else 1. for i,v in enumerate(pixels)])
            img.filepath_raw=str(ROOT/'test-results/mesh-collision-preview.png');img.file_format='PNG';img.save()
        finally:bpy.data.images.remove(img)
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        if target:target.free()
        if solver:solver.close()
        objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:
            data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if data and data.users==0:bpy.data.meshes.remove(data)
        (ROOT/'test-results/mesh-preview-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_MESH_PREVIEW',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
