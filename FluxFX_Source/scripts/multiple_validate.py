"""Multi-source GPU sums/order, live controls, and isolated scene fixtures."""
from pathlib import Path
import json,math
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    import bpy
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.timestep import AdaptiveTimestep
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.emission import Emission,Source
    from fluxfx.blender.emitter import create_emitter,create_additional_emitter,prepare_additional_sources
    from fluxfx.blender import runtime
    report={'status':'RUNNING','tests':[]};solver=None;controller=None;scene=None
    old=bpy.context.window.scene
    def check(name,condition,**metrics):
        assert condition,(name,metrics)
        report['tests'].append(dict(name=name,status='PASS',**metrics))
    def error(a,b):return max(abs(x-y) for x,y in zip(a,b))
    try:
        runtime.shutdown()
        settings=PressureSettings(velocity=(0,0,0),angular_speed=0,thermal_lift=0,density_weight=0,
                                  initial_temperature=0,dissipation=0,cooling=0)
        solver=DenseProjectedSmoke(GridSpec((16,)*3),settings)
        sources=[Source((.4,.5,.5),.2,2,40,Emission((.4,.5,.5))),
                 Source((.6,.5,.5),.2,3,-10,Emission((.6,.5,.5)))]
        solver.reset(seed=False);solver.step(.04,sources=sources)
        density=solver.read_density();heat=solver.read_temperature()
        expected=[];expected_heat=[]
        for z in range(16):
            for y in range(16):
                for x in range(16):
                    p=tuple((i+.5)/16 for i in (x,y,z))
                    weights=[max(1-sum((v-c)**2 for v,c in zip(p,s.center))/s.radius**2,0)**2 for s in sources]
                    expected.append(.04*sum(w*s.density_rate for w,s in zip(weights,sources)))
                    expected_heat.append(.04*sum(w*s.heat_rate for w,s in zip(weights,sources)))
        e=error(density,expected);check('additive_overlapping_density',e<2e-6,max_error=e)
        e=error(heat,expected_heat);check('signed_heat_sum',e<2e-5,max_error=e)
        table=solver._source_table
        solver.step(.04,sources=sources)
        check('unchanged_table_reused',solver._source_table is table)
        solver.reset(seed=False);solver.step(.04,sources=list(reversed(sources)))
        check('scalar_order_independent',error(density,solver.read_density())<2e-6 and error(heat,solver.read_temperature())<2e-5)
        solver.reset(seed=False);solver.step(.04,sources=[])
        check('empty_batch_emits_nothing',max(solver.read_density())==0 and max(map(abs,solver.read_temperature()))==0)
        many=[Source((.5,.5,.5),.2,1,2,Emission((.5,.5,.5))) for _ in range(8)]
        solver.reset(seed=False);solver.step(.04,sources=many)
        eight=solver.read_density()
        solver.reset(seed=False);solver.step(.04,sources=many[:1])
        check('all_eight_sources_contribute',error(eight,[8*v for v in solver.read_density()])<2e-6)
        count=solver.steps
        try:solver.step(.04,sources=many+[many[0]]);raise AssertionError('capacity not enforced')
        except ValueError:check('capacity_rejected_before_step',solver.steps==count and not solver.faulted)
        jets=[Source((.5,)*3,.2,0,0,Emission((.5,)*3,(1,0,0),10)),
              Source((.5,)*3,.2,0,0,Emission((.5,)*3,(0,0,1),20))]
        solver.reset(seed=False);solver.step(.04,sources=jets);vel=solver.read_velocity()
        check('both_jet_directions_present',max(vel[0])>.01 and max(vel[2])>.01)
        metrics=solver.measure_projection();check('multi_jet_projection',metrics['ratio']<.1,ratio=metrics['ratio'])
        solver.reset(seed=False);solver.step(.04,sources=jets[::-1]);reverse=solver.read_velocity()
        check('jet_order_independent',max(error(a,b) for a,b in zip(vel,reverse))<2e-6)
        # A single table row must match the original source path, including a sweep and jet.
        motion=Emission((.3,.5,.16),(0,0,.5),10)
        primary=Source(settings.source_center,settings.source_radius,settings.source_rate,settings.heat_source_rate,motion)
        solver.reset(seed=False);solver.step(.04,motion);a=solver.read_density();av=solver.read_velocity()
        solver.reset(seed=False);solver.step(.04,sources=[primary]);b=solver.read_density();bv=solver.read_velocity()
        check('single_source_compatibility',error(a,b)<2e-6 and max(error(x,y) for x,y in zip(av,bv))<2e-6)
        controller=AdaptiveTimestep(solver.grid,solver.device);solver.reset(seed=False)
        fast=Source((.5,)*3,.2,0,0,Emission((.5,)*3,(10,0,0),10))
        report_dt=controller.select(solver,.04,.75,sources=[jets[0],fast])
        check('adaptive_sees_additional_jet',report_dt['dt']<.01,dt=report_dt['dt'])
        scene=bpy.data.scenes.new('FluxFX Multiple Test');bpy.context.window.scene=scene
        p=scene.fluxfx;p.resolution='16';p.initial_temperature=0;p.thermal_lift=0;p.density_weight=0
        primary_obj=create_emitter(scene);second=create_additional_emitter(scene)
        second.location=(.2,0,-.25);bpy.context.view_layer.update()
        check('additional_creation_preserves_primary',p.emitter_object==primary_obj and len(p.extra_emitters)==1 and second.parent==p.domain_object)
        runtime.initialize(scene);identity=runtime.STATE.solver;runtime.step(scene)
        entry=p.extra_emitters[0];entry.emission_velocity=(1,0,0);second.location.x+=.1;bpy.context.view_layer.update();runtime.step(scene)
        check('live_extra_move_keeps_fields',runtime.STATE.solver is identity and identity.steps==2)
        entry.emission_enabled=False;runtime.step(scene)
        check('disabled_entry_clears_own_history',entry.name not in runtime.STATE.additional_history)
        entry.emission_enabled=True
        additional,_=prepare_additional_sources(scene,runtime.STATE.additional_history)
        check('reenable_has_no_stale_trail',additional[0].motion.start==additional[0].center)
        entry.emitter_object=None;entry.emission_enabled=False;runtime.step(scene)
        check('disabled_missing_object_ignored',identity.steps==4)
        entry.emission_enabled=True;count=identity.steps
        try:runtime.step(scene);raise AssertionError('missing source accepted')
        except ValueError:check('enabled_missing_object_rejected_before_step',identity.steps==count)
        entry.emitter_object=second
        # Removal keeps the object and existing solver; no reset.
        bpy.ops.fluxfx.remove_emitter(index=0);runtime.step(scene)
        check('remove_entry_retains_object_and_solver',second.name in scene.objects and not p.extra_emitters and runtime.STATE.solver is identity)
        for _ in range(7):create_additional_emitter(scene)
        try:create_additional_emitter(scene);raise AssertionError('UI capacity not enforced')
        except ValueError:check('ui_capacity_seven_extras',len(p.extra_emitters)==7)
        runtime.pause();check('pause_clears_all_histories',runtime.STATE.additional_history is None and runtime.STATE.emission_history is None)
        report['status']='PASS'
    except Exception as exc:
        report['status']='FAIL';report['error']=repr(exc);raise
    finally:
        runtime.shutdown()
        if controller:controller.close()
        if solver:
            solver.close()
            check('source_table_released',solver._source_table is None)
        bpy.context.window.scene=old
        if scene:
            for obj in list(scene.objects):bpy.data.objects.remove(obj,do_unlink=True)
            bpy.data.scenes.remove(scene)
        dest=ROOT/'test-results/multiple-validation.json';dest.parent.mkdir(exist_ok=True)
        dest.write_text(json.dumps(report,indent=2));print(report)
    return report

if __name__=='__main__':run_suite()
