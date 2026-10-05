"""Actual scene controls for ignition, fuel emitters and reset lifecycle."""
from pathlib import Path
import json,traceback
import bpy
from fluxfx.blender import runtime
from fluxfx.blender.emitter import create_additional_emitter,prepare_additional_sources
ROOT=Path(__file__).resolve().parents[1]

def run():
    report={'status':'RUNNING','tests':[]}
    old=bpy.context.window.scene;scene=bpy.data.scenes.new('FluxFX Combustion Test');bpy.context.window.scene=scene
    p=scene.fluxfx;p.resolution='32';p.show_preview=False
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    def finish():
        runtime.shutdown();objects=list(scene.objects);bpy.context.window.scene=old;bpy.data.scenes.remove(scene)
        for obj in objects:
            if obj.users==0:bpy.data.objects.remove(obj)
        (ROOT/'test-results/combustion-ui-validation.json').write_text(json.dumps(report,indent=2))
        print('FLUXFX_COMBUSTION_UI',report['status'],report.get('traceback',''))
    try:
        check('fire_preset_registers',bpy.ops.fluxfx.fire_preset()=={'FINISHED'})
        s=runtime.STATE.solver
        check('preset_allocates_fuel',s.combustion is not None and p.source_rate==0 and p.preview_channel=='FLAME')
        for _ in range(30):runtime.step(scene)
        flame=s.device.read(s.combustion.flame,s.grid.shape)
        check('preset_ignites',max(flame)>0 and max(s.read_density())>0)
        p.burn_rate=2;runtime.step(scene)
        check('burn_rate_is_live',runtime.STATE.solver is s and s.settings.burn_rate==2)
        p.emission_enabled=False;runtime.step(scene)
        check('disable_emission_disables_fuel',s.settings.fuel_source_rate==0)
        create_additional_emitter(scene);scene.fluxfx.extra_emitters[0].fuel_source_rate=3
        sources,_=prepare_additional_sources(scene,None)
        check('additional_fuel_control',sources[0].fuel_rate==3)
        runtime.start(scene)
        def done():
            try:
                check('combustion_timer_runs',runtime.STATE.running and s.steps>31 and not runtime.STATE.error)
                p.combustion_enabled=False;runtime.tick()
                check('mode_change_requires_reset',not runtime.STATE.running and 'Reset' in runtime.STATE.error)
                runtime.initialize(scene)
                check('disabled_mode_releases_fuel',runtime.STATE.solver.combustion is None)
                report['status']='PASS'
            except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
            finish();return None
        bpy.app.timers.register(done,first_interval=.4)
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc();finish()
if __name__=='__main__':run()
