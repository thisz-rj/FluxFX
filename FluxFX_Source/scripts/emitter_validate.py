"""Object mapping, live GPU injection, animation and missing-source checks."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    import bpy
    from fluxfx.blender.emitter import create_emitter,source_geometry
    from fluxfx.blender.domain import create_domain
    from fluxfx.blender import runtime
    old_scene=bpy.context.window.scene
    scene=bpy.data.scenes.new('FluxFX Emitter Test');bpy.context.window.scene=scene
    props=scene.fluxfx
    names=('domain_object','emitter_object','source_mode','resolution','source_center','source_radius','source_rate',
           'heat_source_rate','initial_temperature','thermal_lift','density_weight','dissipation','cooling',
           'rise_speed','swirl','adaptive_dt','time_step','emission_enabled','continuous_trails')
    saved={n:tuple(getattr(props,n)) if n=='source_center' else getattr(props,n) for n in names}
    oldframe=scene.frame_current
    report={'status':'RUNNING','tests':[]}
    domain=emitter=None
    def check(name,condition):
        assert condition,name
        report['tests'].append({'name':name,'status':'PASS'})
    def close(a,b,tol=2e-6):return max(abs(x-y) for x,y in zip(a,b))<tol
    try:
        runtime.shutdown()
        props.continuous_trails=False
        props.domain_object=None;props.emitter_object=None;props.source_mode='MANUAL'
        props.source_center=(.25,.5,.5);props.source_radius=.18
        domain=create_domain(scene);emitter=create_emitter(scene)
        bpy.context.view_layer.update()
        center,radius=source_geometry(scene)
        check('creation_and_reuse',create_emitter(scene) is emitter and emitter.parent is domain and close(center,(.25,.5,.5)) and abs(radius-.18)<1e-6)
        domain.location=(1,2,3);domain.rotation_euler=(.3,.5,.7);domain.scale=(2,.5,1.2)
        bpy.context.view_layer.update()
        center,radius=source_geometry(scene)
        check('domain_transform_cancels_for_parented_emitter',close(center,(.25,.5,.5)) and abs(radius-.18)<1e-6)
        props.resolution='16';props.source_rate=2;props.heat_source_rate=30;props.initial_temperature=0
        props.thermal_lift=0;props.density_weight=0;props.dissipation=0;props.cooling=0;props.rise_speed=0;props.swirl=0
        props.adaptive_dt=False;props.time_step=.04;props.emission_enabled=True
        runtime.initialize(scene);solver=runtime.STATE.solver;solver.reset(seed=False)
        runtime.step(scene)
        before=solver.read_density();heat=solver.read_temperature()
        emitter.location.x=.25;emitter.scale=(.15,)*3
        bpy.context.view_layer.update()
        runtime.step(scene)
        check('move_resize_preserve_solver',runtime.STATE.solver is solver and solver.steps==2)
        center,radius=source_geometry(scene)
        expected=[]
        for z in range(16):
            for y in range(16):
                for x in range(16):
                    distance=sum(((v+.5)/16-c)**2 for v,c in zip((x,y,z),center))
                    expected.append(max(1-distance/radius**2,0)**2)
        density=solver.read_density();temperature=solver.read_temperature();dt=props.time_step
        check('new_density_matches_object_injection',max(abs(a-b-dt*2*w) for a,b,w in zip(density,before,expected))<2e-6)
        check('new_heat_matches_object_injection',max(abs(a-b-dt*30*w) for a,b,w in zip(temperature,heat,expected))<2e-5)
        props.emission_enabled=False;runtime.step(scene)
        check('emission_off_keeps_existing_smoke',close(density,solver.read_density()) and close(temperature,solver.read_temperature(),2e-5))
        emitter.scale=(.1,.2,.15);bpy.context.view_layer.update()
        check('nonuniform_uses_largest_axis',abs(source_geometry(scene)[1]-.2)<1e-6)
        emitter.location.x=-.25;emitter.keyframe_insert(data_path='location',frame=1)
        emitter.location.x=.25;emitter.keyframe_insert(data_path='location',frame=2)
        scene.frame_set(1);a=source_geometry(scene)[0]
        scene.frame_set(2);b=source_geometry(scene)[0]
        check('evaluated_animation_positions',close(a,(.25,.5,.5)) and close(b,(.75,.5,.5)) and solver.steps==3)
        emitter.animation_data_clear()
        emitter.scale=(0,0,0);bpy.context.view_layer.update()
        try:source_geometry(scene);raise AssertionError('zero emitter accepted')
        except ValueError:check('zero_size_rejected',True)
        emitter.scale=(.15,)*3;bpy.context.view_layer.update()
        runtime.start(scene);count=solver.steps
        scene.collection.objects.unlink(emitter)
        runtime.tick()
        check('missing_emitter_pauses_without_step',not runtime.STATE.running and solver.steps==count and 'missing' in runtime.STATE.error.lower())
        runtime.pause();scene.collection.objects.link(emitter)
        props.source_mode='MANUAL'
        check('manual_mode_remains_available',close(source_geometry(scene)[0],props.source_center))
        report['status']='PASS'
    except Exception as exc:
        report['status']='FAIL';report['error']=repr(exc)
        raise
    finally:
        runtime.shutdown()
        for obj in (emitter,domain):
            if obj is not None:bpy.data.objects.remove(obj,do_unlink=True)
        for name,value in saved.items():setattr(props,name,value)
        scene.frame_set(oldframe)
        bpy.context.window.scene=old_scene
        bpy.data.scenes.remove(scene)
        (ROOT/'test-results/emitter-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_EMITTER',report)
    return report

if __name__=='__main__':run_suite()
