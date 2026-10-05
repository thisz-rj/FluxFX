"""Direct-keyframe signature persistence and unsupported dependency checks."""
from pathlib import Path
import sys,tempfile,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import bpy,fluxfx
from fluxfx.blender.animation import animation_signature
from fluxfx.blender.emitter import create_emitter
fluxfx.register();scene=bpy.context.scene;emitter=create_emitter(scene)
scene.fluxfx.cache_animated=True
for f,x in [(1,-.2),(8,.2)]:
    emitter.location.x=x;emitter.keyframe_insert(data_path='location',frame=f)
scene.frame_set(3);before=animation_signature(scene)
with tempfile.TemporaryDirectory(prefix='fluxfx-animation-save-') as folder:
    path=str(Path(folder)/'animation.blend');bpy.ops.wm.save_as_mainfile(filepath=path);bpy.ops.wm.open_mainfile(filepath=path)
    scene=bpy.context.scene
    assert scene.fluxfx.cache_animated and animation_signature(scene)==before
    scene.frame_set(6);assert animation_signature(scene)==before
    emitter=scene.fluxfx.emitter_object;constraint=emitter.constraints.new('LIMIT_LOCATION')
    try:animation_signature(scene);raise AssertionError('constraint accepted')
    except ValueError:pass
    emitter.constraints.remove(constraint)
    driver=emitter.driver_add('scale',0)
    try:animation_signature(scene);raise AssertionError('driver accepted')
    except ValueError:pass
    emitter.driver_remove('scale',0)
    emitter.animation_data.nla_tracks.new()
    try:animation_signature(scene);raise AssertionError('NLA accepted')
    except ValueError:pass
report=dict(status='PASS',checks=['animation_signature_save_load','animated_mode_saved','frame_independent_signature','constraints_rejected','drivers_rejected','nla_rejected'])
(ROOT/'test-results/animation-cpu-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_ANIMATION_CPU',report)
fluxfx.unregister()
