"""Run in graphical Blender with the region operator registered."""
from pathlib import Path
import json,traceback
import bpy
from fluxfx.blender import regions,runtime
from fluxfx.blender.emitter import create_emitter,create_additional_emitter
from fluxfx.native import fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
report=dict(status='RUNNING',tests=[])
original=bpy.context.window.scene
scene=bpy.data.scenes.new('FluxFX Region Validation')
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
def check(name,value):
 assert value,name
 report['tests'].append(name)
def cleanup():
 regions.shutdown();bpy.context.window.scene=original
 for obj in list(scene.objects):bpy.data.objects.remove(obj,do_unlink=True)
 bpy.data.scenes.remove(scene)
def finish():
 try:
  check('scene_switch_timer_cleanup',regions.pool is None and regions.handler is None and not bpy.app.timers.is_registered(regions.tick))
  check('owned_bytes_restored',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
  report['status']='PASS'
 except Exception:report.update(status='FAIL',error=traceback.format_exc())
 finally:
  cleanup()
  (ROOT/'test-results/regions-ui-validation.json').write_text(json.dumps(report,indent=2))
 return None
try:
 bpy.context.window.scene=scene
 props=scene.fluxfx;props.native_budget_mb=16;props.sparse_grid=128;props.sparse_halo=0;props.sparse_linger=3
 obj=create_emitter(scene);obj.scale=(.03,)*3;obj.location=(-.3,0,0)
 bpy.context.view_layer.update()
 check('start_operator',bpy.ops.fluxfx.regions()=={'FINISHED'})
 check('timer_and_overlay_registered',regions.handler is not None and bpy.app.timers.is_registered(regions.tick))
 # Stop automatic callbacks while testing exact step counts.
 bpy.app.timers.unregister(regions.tick)
 before={tuple(row[:3]) for row in regions.pool.snapshot()}
 obj.location.x=.3;bpy.context.view_layer.update();regions.step(scene)
 rows=regions.pool.snapshot()
 check('object_movement',any(tuple(r[:3]) not in before for r in rows))
 check('retained_color_batch',any(r[4]==1 for r in rows) and len(regions.batches)==2)
 regions.step(scene);regions.step(scene)
 check('expired_old_bricks',not before.intersection(tuple(r[:3]) for r in regions.pool.snapshot()))
 extra=create_additional_emitter(scene);extra.scale=(.03,)*3;extra.location=(-.3,0,0)
 bpy.context.view_layer.update();regions.step(scene)
 check('multiple_emitters',before.issubset({tuple(r[:3]) for r in regions.pool.snapshot()}))
 props.emission_enabled=False;props.extra_emitters[0].emission_enabled=False
 for _ in range(3):regions.step(scene)
 check('disabled_sources_expire',regions.pool.snapshot()==[] and regions.batches==[])
 props.emission_enabled=True
 regions.start(scene);runtime.before_undo(None)
 check('undo_cleanup',regions.pool is None and regions.handler is None)
 regions.start(scene);runtime.before_load(None)
 check('load_cleanup',regions.pool is None and regions.handler is None)
 regions.start(scene);props.sparse_grid=256;regions.tick()
 check('settings_change_cleanup',regions.pool is None and 'Settings changed' in regions.message)
 regions.start(scene)
 check('stop_operator',bpy.ops.fluxfx.regions(action='STOP')=={'FINISHED'} and regions.pool is None)
 regions.start(scene);bpy.context.window.scene=original
 bpy.app.timers.register(finish,first_interval=.5)
except Exception:
 report.update(status='FAIL',error=traceback.format_exc());cleanup()
 (ROOT/'test-results/regions-ui-validation.json').write_text(json.dumps(report,indent=2))
