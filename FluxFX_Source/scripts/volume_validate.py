"""Render known constant volumes to a float framebuffer and verify optical depth."""
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]


def run_suite():
    import gpu
    from fluxfx.blender.preview import SlicePreview
    from fluxfx.backend.device import BlenderGPUDevice
    renderer=SlicePreview(volume=True)
    device=BlenderGPUDevice()
    target=gpu.types.GPUOffScreen(512,512,format='RGBA32F')
    report={'status':'RUNNING','tests':[]}
    previous=(gpu.state.blend_get(),gpu.state.depth_test_get(),gpu.state.depth_mask_get())
    try:
        with target.bind():
            gpu.state.blend_set('NONE'); gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
            for name,value,forward,right,up,thermal in (
                ('empty',0,(0,1,0),(1,0,0),(0,0,1),False),
                ('linear_x_field',1,(0,1,0),(1,0,0),(0,0,1),False),
                ('constant_front',1,(0,1,0),(1,0,0),(0,0,1),False),
                ('constant_side',1,(1,0,0),(0,1,0),(0,0,1),False),
                ('constant_diagonal',1,(1/math.sqrt(3),)*3,(1/math.sqrt(2),-1/math.sqrt(2),0),(1/math.sqrt(6),1/math.sqrt(6),-2/math.sqrt(6)),False),
                ('cold_temperature',-100,(0,1,0),(1,0,0),(0,0,1),True)):
                tex=device.texture((8,8,8), [(i%8+.5)/8 for i in range(512)] if name=='linear_x_field' else [value]*512,nonnegative=False)
                for samples in (64,128,256):
                    shader=renderer.shader; shader.bind()
                    for key,val in {'viewportSize':(512,512),'uiScale':1,'exposure':2,'thermalView':float(thermal),
                                    'viewForward':forward,'viewRight':right,'viewUp':up}.items():
                        shader.uniform_float(key,val)
                    shader.uniform_int('raySteps',samples); shader.uniform_sampler('densityField',tex)
                    renderer.batch.draw(shader)
                    result=gpu.state.active_framebuffer_get().read_color(154,178,1,1,4,0,'FLOAT')
                    result.dimensions=4
                    actual=list(result)
                    u=(154.5-24)/260-.5; v=(178.5-48)/260-.5
                    origin=[.5-2*f+1.8*(u*r+v*t) for f,r,t in zip(forward,right,up)]
                    near,far=0,4
                    for o,d in zip(origin,forward):
                        if abs(d)>1e-7:
                            a,b=sorted((-o/d,(1-o)/d)); near=max(near,a); far=min(far,b)
                    sampled = origin[0] if name=='linear_x_field' else value
                    optical=(abs(sampled)/100 if thermal else max(sampled,0))*max(0,far-near)*2
                    trans=math.exp(-optical)
                    bg=(.018,.029,.044); tint=(.1,.4,1) if thermal else (.67,.84,.94)
                    expected=[c*(1-trans)+b*trans for c,b in zip(tint,bg)]+[1]
                    error=max(abs(a-b) for a,b in zip(actual,expected))
                    corner=gpu.state.active_framebuffer_get().read_color(24,48,1,1,4,0,'FLOAT')
                    corner.dimensions=4
                    assert max(abs(a-b) for a,b in zip(corner,(*bg,1)))<2e-6, 'miss ray'
                    assert error<2e-5,(name,samples,actual,expected,error)
                    report['tests'].append({'name':name,'samples':samples,'max_error':error,'status':'PASS'})
            report['status']='PASS'
    finally:
        gpu.state.blend_set(previous[0]); gpu.state.depth_test_set(previous[1]); gpu.state.depth_mask_set(previous[2])
        target.free()
    (ROOT/'test-results/volume-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_VOLUME',report)
    return report


if __name__=='__main__': run_suite()
