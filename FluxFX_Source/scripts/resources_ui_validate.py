"""Run after registration, in graphical Blender; waits for scene-change cleanup."""
from pathlib import Path
import bpy,json,traceback
from fluxfx.blender import native_runtime,runtime
from fluxfx.native import fluxfx_core
ROOT=Path(__file__).resolve().parents[1]

def run():
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX P1 Resource UI Test')
    bpy.context.window.scene=scene;scene.fluxfx.native_budget_mb=1
    baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
    report=dict(status='RUNNING',tests=[])
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    def finish():
        native_runtime.shutdown();bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        (ROOT/'test-results/resources-ui-validation.json').write_text(json.dumps(report,indent=2))
        print('FLUXFX_RESOURCES_UI',report['status'],report.get('traceback',''))
    def delayed():
        try:
            check('scene_timer_releases_context',native_runtime.context is None and fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
            check('scene_timer_removed',not bpy.app.timers.is_registered(native_runtime.watch_scene))
            report['status']='PASS'
        except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
        finish();return None
    try:
        check('operator_success',bpy.ops.fluxfx.native_resources()=={'FINISHED'})
        check('context_retained_within_budget',native_runtime.context.stats()['resident_bytes']==2**20 and native_runtime.context.stats()['used_bytes']==0)
        check('report_text',json.loads(bpy.data.texts['FluxFX Native Resources.json'].as_string())['status']=='PASS')
        bpy.ops.fluxfx.native_resources();check('operator_reuses_context',native_runtime.context.stats()['allocation_requests']==2)
        bpy.ops.fluxfx.native_resources(action='RELEASE')
        check('release_operator_cleanup',native_runtime.context is None and fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
        bpy.ops.fluxfx.native_resources();runtime.before_undo(None)
        check('undo_cleanup',native_runtime.context is None)
        bpy.ops.fluxfx.native_resources();runtime.before_load(None)
        check('load_cleanup',native_runtime.context is None)
        bpy.ops.fluxfx.native_resources();bpy.context.window.scene=old
        bpy.app.timers.register(delayed,first_interval=.5)
    except Exception:
        report['status']='FAIL';report['traceback']=traceback.format_exc();finish()
if __name__=='__main__':run()
