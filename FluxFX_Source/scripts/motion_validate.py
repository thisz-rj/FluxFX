"""0.13 real GPU trail, velocity, projection and Blender history checks."""
from pathlib import Path
import json, math
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    import bpy
    from fluxfx.blender import runtime
    from fluxfx.blender.emitter import create_emitter, prepare_emission, emission_snapshot
    from fluxfx.physics.emission import Emission
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.timestep import AdaptiveTimestep
    report={'status':'RUNNING','tests':[]}
    def check(name,condition,**metrics):
        assert condition, (name,metrics)
        report['tests'].append(dict(name=name,status='PASS',**metrics))
    solver=None;controller=None;scene=None
    old=bpy.context.window.scene
    try:
        runtime.shutdown()
        n=16;dt=.04;r=.15;a=(.2,.5,.5);b=(.8,.5,.5)
        settings=PressureSettings(velocity=(0,0,0),angular_speed=0,source_center=b,source_radius=r,
            source_rate=2,heat_source_rate=30,thermal_lift=0,density_weight=0,initial_temperature=0,dissipation=0,cooling=0)
        solver=DenseProjectedSmoke(GridSpec((n,n,n)),settings)
        solver.reset(seed=False);solver.step(dt,Emission(a))
        density=solver.read_density();heat=solver.read_temperature()
        expected=[]
        # Independent midpoint quadrature of moving spheres, not the shader's antiderivative.
        for z in range(n):
            for y in range(n):
                for x in range(n):
                    p=((x+.5)/n,(y+.5)/n,(z+.5)/n)
                    total=0
                    for i in range(256):
                        c=a[0]+(b[0]-a[0])*(i+.5)/256
                        d=(p[0]-c)**2+(p[1]-.5)**2+(p[2]-.5)**2
                        total+=max(1-d/r**2,0)**2
                    expected.append(total/256)
        error=max(abs(v-dt*2*w) for v,w in zip(density,expected))
        check('swept_density_matches_quadrature',error<2e-6,max_error=error)
        error=max(abs(v-dt*30*w) for v,w in zip(heat,expected))
        check('swept_heat_matches_quadrature',error<3e-5,max_error=error)
        check('trail_has_no_centerline_gaps',all(density[(8*n+8)*n+x]>0 for x in range(3,13)))
        # Reverse segment yields the same time-integrated source.
        from dataclasses import replace
        solver.update_settings(replace(settings,source_center=a));solver.reset(seed=False);solver.step(dt,Emission(b))
        check('reverse_sweep_symmetry',max(abs(x-y) for x,y in zip(density,solver.read_density()))<2e-6)
        solver.update_settings(replace(settings,source_center=(.5,.5,.5)))
        for axis in range(3):
            solver.reset(seed=False)
            velocity=tuple(1. if i==axis else 0. for i in range(3))
            solver.step(dt,Emission((.5,.5,.5),velocity,20))
            fields=solver.read_velocity()
            check('jet_axis_'+str(axis),max(fields[axis])>.01 and all(math.isfinite(v) for f in fields for v in f),peak=max(fields[axis]))
            metrics=solver.measure_projection()
            check('projected_jet_'+str(axis),metrics['ratio']<.15,ratio=metrics['ratio'])
        controller=AdaptiveTimestep(solver.grid,solver.device)
        solver.reset(seed=False)
        plain=controller.select(solver,.04,.75)
        forced=controller.select(solver,.04,.75,Emission((.5,.5,.5),(10,0,0),20))
        check('adaptive_step_accounts_for_jet',forced['dt']<plain['dt'],dt=forced['dt'])
        scene=bpy.data.scenes.new('FluxFX Motion Test');bpy.context.window.scene=scene
        p=scene.fluxfx;p.source_center=(.25,.5,.5);p.source_radius=.15
        emitter=create_emitter(scene);bpy.context.view_layer.update()
        p.emission_velocity=(0,0,1);emitter.rotation_euler.y=math.pi/2;bpy.context.view_layer.update()
        snapshot=emission_snapshot(scene)
        check('jet_follows_rotation',abs(snapshot[1][0]-1)<1e-5 and abs(snapshot[1][2])<1e-5)
        p.emission_velocity=(0,0,0);p.motion_inheritance=1;p.time_step=.04;p.motion_speed_limit=2
        previous=emission_snapshot(scene);emitter.location.x+=.5;bpy.context.view_layer.update()
        emission,current=prepare_emission(scene,previous)
        check('motion_capped_and_path_preserved',abs(emission.velocity[0]-2)<1e-6 and emission.start==previous[0])
        p.emission_enabled=False
        emission,_=prepare_emission(scene,previous)
        check('off_disables_velocity_and_trail',emission.coupling==0 and emission.start==current[0])
        p.emission_enabled=True;scene.frame_set(scene.frame_current+10)
        emission,_=prepare_emission(scene,previous)
        check('timeline_jump_resets_history',emission.start==current[0] and emission.velocity==(0,0,0))
        previous=emission_snapshot(scene);emitter.parent.location.x+=1;bpy.context.view_layer.update()
        emission,_=prepare_emission(scene,previous)
        check('domain_move_resets_history',emission.velocity==(0,0,0))
        p.resolution='16';p.initial_temperature=0;p.thermal_lift=0;p.density_weight=0
        runtime.initialize(scene);identity=runtime.STATE.solver
        runtime.step(scene);emitter.location.x-=.2;bpy.context.view_layer.update();runtime.step(scene)
        check('live_motion_preserves_solver',runtime.STATE.solver is identity and identity.steps==2)
        runtime.pause();check('pause_clears_motion_history',runtime.STATE.emission_history is None)
        report['status']='PASS'
    except Exception as exc:
        report['status']='FAIL';report['error']=repr(exc)
        raise
    finally:
        runtime.shutdown()
        if controller:controller.close()
        if solver:solver.close()
        bpy.context.window.scene=old
        if scene:
            for obj in list(scene.objects):bpy.data.objects.remove(obj,do_unlink=True)
            bpy.data.scenes.remove(scene)
        dest=ROOT/'test-results/motion-validation.json';dest.parent.mkdir(exist_ok=True)
        dest.write_text(json.dumps(report,indent=2));print(report)
    return report

if __name__=='__main__':run_suite()
