"""Scene-volume pixel oracles and domain transforms in graphical Blender."""
from pathlib import Path
from math import tan, radians, exp
import json
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    import bpy,gpu
    from mathutils import Matrix,Vector,Euler
    from fluxfx.blender.scene_preview import ScenePreview
    from fluxfx.blender.domain import clip_to_domain,create_domain,domain_object
    from fluxfx.backend.device import BlenderGPUDevice
    from fluxfx.backend.diagnostics import collect
    from fluxfx.blender import runtime
    runtime.pause()
    report={'status':'RUNNING','diagnostics':collect(True),'tests':[]}
    renderer=ScenePreview();device=BlenderGPUDevice()
    texture=device.texture((8,8,8),[1.]*512)
    target=gpu.types.GPUOffScreen(32,24,format='RGBA32F')
    near,far=.1,10
    f=1/tan(radians(55)/2)
    perspective=Matrix(((f/(32/24),0,0,0),(0,f,0,0),(0,0,-(far+near)/(far-near),-2*far*near/(far-near)),(0,0,-1,0)))
    ortho=Matrix(((.75,0,0,0),(0,1,0,0),(0,0,-2/(far-near),-(far+near)/(far-near)),(0,0,0,1)))
    view=Matrix.Translation((0,0,-3))
    bg=(.1,.2,.3,1)
    cases=[('perspective',perspective@view,Matrix.Identity(4)),
           ('orthographic',ortho@view,Matrix.Identity(4)),
           ('moved_rotated_scaled',perspective@view,Matrix.Translation((.35,0,0))@Euler((.3,.6,.2)).to_matrix().to_4x4()@Matrix.Diagonal((1.4,.7,1.2,1))),
           ('inside_camera',perspective,Matrix.Identity(4)),
           ('behind_camera',perspective@view,Matrix.Translation((0,0,5))),
           ('mirrored',perspective@view,Matrix.Diagonal((-1,1,1,1)))]
    def expected(matrix,x,y,value):
        ndc=((x+.5)/32*2-1,(y+.5)/24*2-1)
        a=matrix@Vector((*ndc,-1,1));b=matrix@Vector((*ndc,1,1))
        origin=a.xyz/a.w;direction=b.xyz/b.w-origin
        lo,hi=0.,1.
        for o,d in zip(origin,direction):
            if abs(d)<1e-8:
                if not 0<=o<=1:return list(bg)
            else:
                left,right=sorted((-o/d,(1-o)/d));lo=max(lo,left);hi=min(hi,right)
        distance=max(0,hi-lo)*direction.length
        t=exp(-2*value*distance)
        return [smoke*(1-t)+back*t for smoke,back in zip((.67,.84,.94),bg)]+[1]
    try:
        with target.bind():
            for name,vp,world in cases:
                transform=clip_to_domain(vp,world)
                for samples in (64,128):
                    gpu.state.active_framebuffer_get().clear(color=bg)
                    state=(gpu.state.blend_get(),gpu.state.depth_test_get(),gpu.state.depth_mask_get())
                    renderer.render(texture,transform,2,samples=samples)
                    assert state==(gpu.state.blend_get(),gpu.state.depth_test_get(),gpu.state.depth_mask_get())
                    error=0
                    for x,y in ((16,12),(20,11),(0,0),(12,15),(24,12)):
                        actual=gpu.state.active_framebuffer_get().read_color(x,y,1,1,4,0,'FLOAT');actual.dimensions=4
                        error=max(error,max(abs(a-b) for a,b in zip(actual,expected(transform,x,y,1))))
                    assert error<3e-5,(name,samples,error)
                    report['tests'].append({'name':name,'samples':samples,'max_error':error,'status':'PASS'})
            texture.clear(format='FLOAT',value=(0.,))
            gpu.state.active_framebuffer_get().clear(color=bg)
            renderer.render(texture,clip_to_domain(perspective@view,Matrix.Identity(4)),2)
            actual=gpu.state.active_framebuffer_get().read_color(16,12,1,1,4,0,'FLOAT');actual.dimensions=4
            assert max(abs(a-b) for a,b in zip(actual,bg))<1e-6
            report['tests'].append({'name':'empty_preserves_viewport','status':'PASS'})
    finally:target.free()
    scene=bpy.context.scene
    old=scene.fluxfx.domain_object
    scene.fluxfx.domain_object=None
    obj=create_domain(scene)
    try:
        assert create_domain(scene) is obj and domain_object(scene) is obj
        assert obj.type=='EMPTY' and obj.empty_display_size==.5
        runtime.initialize(scene)
        runtime.step(scene)
        solver=runtime.STATE.solver;steps=solver.steps
        obj.location=(1,2,3);obj.rotation_euler=(.2,.4,.6);obj.scale=(2,.5,1)
        bpy.context.view_layer.update()
        runtime.ensure_current(scene)
        assert runtime.STATE.solver is solver and solver.steps==steps
        report['tests'].append({'name':'domain_creation_reuse_and_transform_preserve_solver','status':'PASS'})
        try:
            clip_to_domain(Matrix.Identity(4),Matrix.Diagonal((0,1,1,1)))
            raise AssertionError('singular matrix accepted')
        except ValueError:pass
        report['tests'].append({'name':'zero_scale_rejected','status':'PASS'})
    finally:
        runtime.shutdown()
        bpy.data.objects.remove(obj,do_unlink=True)
        scene.fluxfx.domain_object=old
    report['status']='PASS'
    (ROOT/'test-results/scene-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_SCENE',report)
    return report

if __name__=='__main__':run_suite()
