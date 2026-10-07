"""Native half of 0.15 comparison; run in a fresh factory-startup Blender process."""
import argparse,json,sys,time,resource,platform,tempfile,gzip,array
from pathlib import Path
import bpy

ROOT=Path(__file__).resolve().parents[1]

def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--grid',type=int,default=64)
    parser.add_argument('--case',choices=('stationary','moving','multiple'),default='stationary')
    parser.add_argument('--frames',type=int,default=60)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    out=ROOT/'test-results/comparison';out.mkdir(parents=True,exist_ok=True)
    tag=f'mantaflow-{args.case}-{args.grid}'
    report={'engine':'Mantaflow','case':args.case,'grid':args.grid,'frames':args.frames,
            'fps':30,'duration_seconds':args.frames/30,'version':bpy.app.version_string,
            'build':bpy.app.build_hash.decode(),'platform':platform.platform(),'status':'RUNNING',
            'frame_ms':[],'density_checkpoints':[],
            'settings':{'domain_meters':1,'radius_meters':.09,'jet_mps':[0,0,.5],
            'density':1,'absolute_inflow':True,'surface_distance_voxels':1,'volume_density':1,
            'cfl':.75,'max_substeps':100,'adaptive_domain':False,'noise':False,
            'gravity_buoyancy_vorticity':False,'closed_borders':True,'cache':'Replay UNI',
            'source_velocity_inheritance':0,'moving_source_sampling_subframes':2}}
    def save(): (out/(tag+'.json')).write_text(json.dumps(report,indent=2))
    save()
    scene=bpy.context.scene
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene.render.fps=30;scene.render.fps_base=1;scene.frame_start=1;scene.frame_end=args.frames
    scene.use_gravity=False
    scene.sync_mode='NONE'
    bpy.ops.mesh.primitive_cube_add(size=1,location=(.5,.5,.5))
    domain=bpy.context.object;domain.name='Benchmark Domain'
    mod=domain.modifiers.new('Mantaflow','FLUID');mod.fluid_type='DOMAIN';d=mod.domain_settings
    d.domain_type='GAS';d.resolution_max=args.grid;d.use_adaptive_domain=False;d.use_noise=False
    d.alpha=0;d.beta=0;d.vorticity=0;d.use_dissolve_smoke=False
    for face in ('front','back','left','right','top','bottom'):setattr(d,'use_collision_border_'+face,True)
    d.use_adaptive_timesteps=True;d.cfl_condition=.75;d.timesteps_min=1;d.timesteps_max=100
    d.cache_type='REPLAY';d.cache_frame_start=1;d.cache_frame_end=args.frames
    d.cache_data_format='UNI'
    emitters=[]
    for x in ((.3,.7) if args.case=='multiple' else ((.25,) if args.case=='moving' else (.5,))):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=.09,location=(x,.5,.2))
        obj=bpy.context.object;obj.name='Benchmark Source'
        flow=obj.modifiers.new('Smoke','FLUID');flow.fluid_type='FLOW';f=flow.flow_settings
        f.flow_type='SMOKE';f.flow_behavior='INFLOW';f.flow_source='MESH'
        f.surface_distance=1;f.volume_density=1;f.density=1;f.temperature=0
        f.use_absolute=True;f.use_initial_velocity=True;f.velocity_coord=(0,0,.5)
        f.velocity_factor=0;f.velocity_normal=0;f.subframes=2
        if args.case=='moving':
            obj.keyframe_insert(data_path='location',frame=1)
            obj.location.x=.75;obj.keyframe_insert(data_path='location',frame=args.frames)
            # Current layered actions expose curves through channel bags.
            action=obj.animation_data.action
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        for curve in bag.fcurves:
                            for point in curve.keyframe_points:point.interpolation='LINEAR'
        emitters.append(obj)
    scene.frame_set(0)
    bpy.context.view_layer.objects.active=domain
    report['rss_before_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with tempfile.TemporaryDirectory(prefix='fluxfx-manta-bench-') as cache:
        d.cache_directory=cache
        begin=time.perf_counter()
        try:
            for frame in range(1,args.frames+1):
                start=time.perf_counter();scene.frame_set(frame);bpy.context.view_layer.update()
                evaluated=domain.evaluated_get(bpy.context.evaluated_depsgraph_get())
                report['frame_ms'].append((time.perf_counter()-start)*1000)
                if frame in (1,args.frames):
                    grid=list(evaluated.modifiers["Mantaflow"].domain_settings.density_grid)
                    report['density_checkpoints'].append({'frame':frame,'cells':len(grid),'maximum':max(grid,default=0),'sum':sum(grid)})
                if frame%10==0:save()
            report['elapsed_including_checkpoints_seconds']=time.perf_counter()-begin
            density=array.array('f',evaluated.modifiers['Mantaflow'].domain_settings.density_grid)
            assert len(density)==args.grid**3 and max(density)>0,'Native density grid empty or incorrect size'
            with gzip.open(out/(tag+'.f32.gz'),'wb') as f:f.write(density.tobytes())
            report['domain_resolution']=list(evaluated.modifiers['Mantaflow'].domain_settings.domain_resolution)
            report['velocity_max_abs']=max(map(abs,evaluated.modifiers['Mantaflow'].domain_settings.velocity_grid),default=0)
            assert report['velocity_max_abs']>0,'Native jet failed to inject velocity'
            report['source_final_locations']=[list(o.evaluated_get(bpy.context.evaluated_depsgraph_get()).location) for o in emitters]
            report['peak_process_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report['cache_bytes']=sum(p.stat().st_size for p in Path(cache).rglob('*') if p.is_file())
            report['simulation_evaluation_seconds']=sum(report['frame_ms'])/1000
            report['status']='PASS'
        except Exception as exc:
            report['status']='FAIL';report['error']=repr(exc);raise
        finally:save()
    print('FLUXFX_NATIVE_COMPARISON',tag,report['status'],report.get('simulation_evaluation_seconds'),flush=True)

if __name__=='__main__':run()
