"""Create an unsaved two-source demo scene without replacing the previous scene."""
import bpy
from fluxfx.blender import runtime
from fluxfx.blender.emitter import create_emitter,create_additional_emitter

runtime.shutdown()
scene=bpy.data.scenes.new('FluxFX 0.14 Two Emitters')
bpy.context.window.scene=scene
p=scene.fluxfx
p.resolution='64';p.source_center=(.3,.5,.2);p.source_radius=.09
p.initial_temperature=0;p.source_rate=6;p.emission_velocity=(.1,0,.8);p.velocity_coupling=20
first=create_emitter(scene)
second=create_additional_emitter(scene);second.location=(.2,0,-.3)
entry=p.extra_emitters[0];entry.source_rate=6;entry.emission_velocity=(-.1,0,.8);entry.velocity_coupling=20
p.exposure=8
bpy.context.view_layer.update()
runtime.initialize(scene)
for _ in range(80):runtime.step(scene)
for obj in scene.objects:obj.select_set(False)
p.domain_object.select_set(True);bpy.context.view_layer.objects.active=p.domain_object
runtime.redraw()
print('FluxFX 0.14 two-emitter preview ready; scene is unsaved.')
