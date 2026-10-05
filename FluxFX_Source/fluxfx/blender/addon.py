"""FluxFX sidebar; numerical work lives in physics/backend/shaders."""
import json
import traceback
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, CollectionProperty, StringProperty

from ..backend.diagnostics import collect
from ..version import VERSION_LABEL
from . import runtime, cache, native_runtime, regions
from .domain import create_domain
from .collider import create_collider, update_display_shape
from .emitter import create_emitter, create_additional_emitter


class FluxFXEmitterProperties(bpy.types.PropertyGroup):
    source_mode: EnumProperty(items=[("OBJECT","Object","Spherical source")],default="OBJECT")
    emitter_object: PointerProperty(name="Emitter",type=bpy.types.Object,poll=lambda self,obj:obj.type=="EMPTY")
    emission_enabled: BoolProperty(name="Enabled",default=True)
    expanded: BoolProperty(name="Show controls",default=False)
    fuel_source_rate: FloatProperty(name="Fuel source /s",default=1,min=0,max=10)
    heat_source_rate: FloatProperty(name="Heat source (K/s)",default=100,min=-500,max=1000)
    emission_velocity: FloatVectorProperty(name="Jet velocity (m/s)", size=3, default=(0,0,0), min=-10, max=10, description="Emitter local axes in Object mode; domain axes in Manual mode")
    velocity_coupling: FloatProperty(name="Velocity coupling /s", default=10, min=0, max=100)
    motion_inheritance: FloatProperty(name="Inherit motion", default=0, min=0, max=2)
    motion_speed_limit: FloatProperty(name="Inherited speed limit (m/s)", default=2, min=.01, max=20)
    continuous_trails: BoolProperty(name="Continuous trails", default=True)
    density_mode: EnumProperty(name="Density emission",items=[("RATE","Additive rate","Add density per second"),("TARGET","Target density","Maintain at least a target density in source")],default="RATE")
    source_profile: EnumProperty(name="Source profile",items=[("SOFT","Soft sphere","Smooth compact falloff"),("SOLID","Solid sphere","Uniform interior")],default="SOFT")
    source_rate: FloatProperty(name="Density source /s", default=2, min=0, max=10)


class FluxFXColliderProperties(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Enabled",default=True)
    shape: EnumProperty(name="Shape",items=[("SPHERE","Sphere","Unit sphere; scale to size"),("BOX","Box","Unit box; scale to half-size"),("MESH","Mesh","Closed static mesh; SDF built on Reset")],default="SPHERE",update=update_display_shape)
    collider_object: PointerProperty(name="Collider",type=bpy.types.Object,poll=lambda self,obj:obj.type in {"EMPTY","MESH"})


class FluxFXProperties(bpy.types.PropertyGroup):
    sparse_grid: IntProperty(name="Sparse domain grid",default=256,min=64,max=512,step=8,description="Preview voxel resolution; rounded down to complete 8-voxel bricks")
    sparse_capacity: IntProperty(name="Brick capacity",default=4096,min=64,max=16384)
    sparse_linger: IntProperty(name="Inactive steps",default=3,min=1,max=1000)
    sparse_halo: IntProperty(name="Safety halo (bricks)",default=1,min=0,max=4)
    sparse_speed_margin: FloatProperty(name="Flow speed bound",default=0,min=0,max=20,description="Extra speed bound in domain lengths/second, applied in every direction")
    native_budget_mb: IntProperty(name="Native arena (MiB)",default=64,min=1,max=1024,description="Hard backing-buffer budget for the native context; excludes driver/Blender allocations")
    native_status: StringProperty(name="Native core",default="Not tested")
    cache_animated: BoolProperty(name="Animated inputs",default=False,description="Sample direct keyframes at each baked frame; restore the original timeline frame when finished")
    cache_compress: BoolProperty(name="Lossless compression",default=False,description="Reduce cache storage using fast compression; may increase bake and playback time")
    cache_memory_mb: IntProperty(name="Frame memory (MiB)",default=256,min=0,max=4096,description="Decoded frame pool limit; zero disables retention. Displayed frame, GPU and temporary decode memory are additional")
    cache_prefetch: BoolProperty(name="Prefetch nearby frames",default=True,description="Read up to two frames ahead between playback callbacks; a disk read can briefly occupy the main thread")
    cache_directory: StringProperty(name="Bake folder",subtype="DIR_PATH",default="//fluxfx-cache/")
    cache_path: StringProperty(name="Playback folder",subtype="DIR_PATH",default="")
    cache_start: IntProperty(name="First frame",default=1,min=-1048574,max=1048574)
    cache_end: IntProperty(name="Last frame",default=120,min=-1048574,max=1048574)
    cache_start_empty: BoolProperty(name="Start empty",default=True,description="Begin at zero smoke, heat and fuel; unchecked uses the solver's seeded initial state")

    turbulence_strength: FloatProperty(name="Strength (m/s²)",default=0,min=0,max=20)
    turbulence_scale: FloatProperty(name="Largest size (m)",default=.5,min=.01,max=4)
    turbulence_speed: FloatProperty(name="Evolution speed",default=.5,min=0,max=10)
    turbulence_seed: IntProperty(name="Seed",default=0,min=0,max=65535)
    turbulence_octaves: IntProperty(name="Scales",default=3,min=1,max=4)
    turbulence_limit: FloatProperty(name="Acceleration limit",default=2,min=.01,max=20)
    turbulence_mask: EnumProperty(name="Apply in",items=[('ALL','Everywhere','Force the entire domain'),('DENSITY','Smoke','Scale by smoke density'),('HEAT','Hot regions','Scale by positive temperature excess')],default='DENSITY')
    turbulence_threshold: FloatProperty(name="Full effect at",default=.2,min=.001,max=2000,description="Density units for Smoke; kelvin above ambient for Hot regions")
    combustion_enabled: BoolProperty(name="Combustion · Reset required",default=False)
    ignition_temperature: FloatProperty(name="Ignition excess (K)",default=150,min=0,max=2000)
    burn_rate: FloatProperty(name="Burn rate /s",default=4,min=0,max=50)
    heat_yield: FloatProperty(name="Heat per fuel (K)",default=600,min=0,max=3000)
    smoke_yield: FloatProperty(name="Smoke per fuel",default=1,min=0,max=10)
    moving_colliders: BoolProperty(name="Moving colliders", description="Translation and rotation during playback; GPU Jacobi pressure. Change mode or size with Reset", default=False)
    colliders: CollectionProperty(type=FluxFXColliderProperties)
    extra_emitters: CollectionProperty(type=FluxFXEmitterProperties)
    velocity_advection: EnumProperty(name="Motion transport",items=[("SEMI_LAGRANGIAN","Fast","Original velocity transport"),("MACCORMACK","Detailed","Bounded correction preserves finer motion")],default="MACCORMACK")
    scalar_advection: EnumProperty(name="Smoke transport",items=[("SEMI_LAGRANGIAN","Fast","Original transport"),("MACCORMACK","Detailed","Bounded predictor-corrector for smoke and heat")],default="MACCORMACK")
    vorticity_strength: FloatProperty(name="Curl strength /s",default=0,min=0,max=20)
    vorticity_limit: FloatProperty(name="Curl acceleration limit",default=2,min=.01,max=20)
    source_mode: EnumProperty(name="Source control", items=[("MANUAL", "Manual", "Use position/radius values"), ("OBJECT", "Object", "Use a spherical Empty source")], default="MANUAL")
    emitter_object: PointerProperty(name="Emitter", type=bpy.types.Object, poll=lambda self, obj: obj.type == "EMPTY")
    domain_object: PointerProperty(name="Domain", type=bpy.types.Object, poll=lambda self, obj: obj.type == "EMPTY")
    resolution: EnumProperty(name="Grid", items=[(str(n), f"{n}³", "Dense R32F grid")
                                                 for n in (16, 32, 64, 128)], default="64")
    adaptive_dt: BoolProperty(name="Adaptive timestep", default=True)
    cfl_target: FloatProperty(name="CFL target", default=0.75, min=0.1, max=2.0)
    playback_budget_ms: FloatProperty(name="Playback budget (ms)", default=24, min=1, max=100,
        description="Soft work budget per callback; one GPU step may exceed it")
    time_step: FloatProperty(name="Max step (seconds)", default=1 / 30, min=0.001, max=0.1)
    rise_speed: FloatProperty(name="Initial rise (m/s)", default=0.0, min=-2, max=2)
    swirl: FloatProperty(name="Initial rotation (rad/s)", default=0.0, min=-5, max=5)
    emission_enabled: BoolProperty(name="Emit smoke, heat and fuel", default=True,
        description="Turn emission off while existing smoke continues to evolve")
    source_center: FloatVectorProperty(name="Source position (m)", size=3,
        default=(0.5, 0.5, 0.16), min=0.0, max=1.0, subtype="XYZ")
    source_radius: FloatProperty(name="Source radius (m)", default=0.12, min=0.01, max=0.5)
    emission_velocity: FloatVectorProperty(name="Jet velocity (m/s)", size=3, default=(0,0,0), min=-10, max=10, description="Emitter local axes in Object mode; domain axes in Manual mode")
    velocity_coupling: FloatProperty(name="Velocity coupling /s", default=10, min=0, max=100)
    motion_inheritance: FloatProperty(name="Inherit motion", default=0, min=0, max=2)
    motion_speed_limit: FloatProperty(name="Inherited speed limit (m/s)", default=2, min=.01, max=20)
    continuous_trails: BoolProperty(name="Continuous trails", default=True)
    density_mode: EnumProperty(name="Density emission",items=[("RATE","Additive rate","Add density per second"),("TARGET","Target density","Maintain at least a target density in source")],default="RATE")
    source_profile: EnumProperty(name="Source profile",items=[("SOFT","Soft sphere","Smooth compact falloff"),("SOLID","Solid sphere","Uniform interior")],default="SOFT")
    source_rate: FloatProperty(name="Density source /s", default=2, min=0, max=10)
    dissipation: FloatProperty(name="Decay /s", default=0.1, min=0, max=5)
    initial_temperature: FloatProperty(name="Initial heat (K)", default=100, min=-500, max=1000)
    fuel_source_rate: FloatProperty(name="Fuel source /s",default=1,min=0,max=10)
    heat_source_rate: FloatProperty(name="Heat source (K/s)", default=100, min=-500, max=1000)
    cooling: FloatProperty(name="Cooling /s", default=0.5, min=0, max=10)
    thermal_lift: FloatProperty(name="Heat lift (m/s²/K)", default=0.005, min=0, max=0.1, precision=4)
    density_weight: FloatProperty(name="Density weight (m/s²)", default=0.05, min=0, max=2)
    pressure_solver: EnumProperty(name="Pressure solver", items=[
        ("AUTO", "Auto", "Multigrid for coarsenable grids from 16³; Jacobi fallback"),
        ("JACOBI", "Jacobi", "Original weighted Jacobi baseline"),
        ("MULTIGRID", "Multigrid", "Coarse-grid correction; Jacobi fallback for uncoarsenable grids")], default="AUTO")
    pressure_cycles: IntProperty(name="Multigrid cycles", default=2, min=1, max=16)
    pressure_iterations: IntProperty(name="Pressure iterations @64³", default=80, min=1, max=1024,
        description="Base Jacobi budget; scales with resolution squared. Cold solves use 4x; capped at 4096")
    preview_mode: EnumProperty(name="View", items=[("SCENE", "Scene volume", "Volume placed by the domain object; no scene occlusion yet"), ("VOLUME", "3D inset", "Orthographic inset follows viewport rotation"),
        ("SLICE", "XZ slice", "Diagnostic cross section")], default="SCENE")
    ray_steps: EnumProperty(name="Ray samples", items=[(str(n), str(n), "Samples per ray") for n in (64,128,256)], default="128")
    preview_channel: EnumProperty(name="Display", items=[("DENSITY", "Density", "Smoke density"), ("COLLISION", "Collision mask", "Resolved voxel obstacles"),
        ("FUEL", "Fuel", "Unburned fuel"), ("FLAME", "Flame", "Burning-rate preview; approximate colours"),
        ("TEMPERATURE", "Temperature", "Excess over ambient: warm orange, cold blue")], default="DENSITY")
    show_preview: BoolProperty(name="Show preview", default=True)
    slice_y: FloatProperty(name="Y slice", default=0.5, min=0.0, max=1.0)
    exposure: FloatProperty(name="Opacity scale", default=3, min=0.1, max=20)


class FLUXFX_OT_fire_preset(bpy.types.Operator):
    bl_idname="fluxfx.fire_preset"
    bl_label="Use Basic Fire Settings"
    bl_description="Set primary source fuel/heat and combustion rates, then Reset; replaces primary fire controls"
    bl_options={"REGISTER","UNDO"}

    def execute(self,context):
        runtime.pause()
        p=context.scene.fluxfx
        p.combustion_enabled=True;p.emission_enabled=True
        p.fuel_source_rate=1;p.heat_source_rate=1000;p.source_rate=0
        p.ignition_temperature=150;p.burn_rate=4;p.heat_yield=600;p.smoke_yield=1
        p.initial_temperature=0;p.cooling=.5;p.thermal_lift=.005
        p.preview_channel='FLAME'
        try:
            runtime.initialize(context.scene)
            runtime.STATE.solver.reset(seed=False)
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}
        return {'FINISHED'}


class FLUXFX_OT_domain(bpy.types.Operator):
    bl_idname = "fluxfx.create_domain"
    bl_label = "Create Smoke Domain"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = create_domain(context.scene)
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        runtime.redraw()
        return {"FINISHED"}


class FLUXFX_OT_emitter(bpy.types.Operator):
    bl_idname = "fluxfx.create_emitter"
    bl_label = "Create Smoke Emitter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = create_emitter(context.scene)
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        runtime.redraw()
        return {"FINISHED"}


class FLUXFX_OT_add_emitter(bpy.types.Operator):
    bl_idname="fluxfx.add_emitter"
    bl_label="Add Another Emitter"
    bl_options={"REGISTER","UNDO"}

    def execute(self,context):
        try:obj=create_additional_emitter(context.scene)
        except ValueError as exc:
            self.report({"ERROR"},str(exc));return {"CANCELLED"}
        for selected in context.selected_objects:selected.select_set(False)
        obj.select_set(True);context.view_layer.objects.active=obj
        runtime.redraw()
        return {"FINISHED"}


class FLUXFX_OT_remove_emitter(bpy.types.Operator):
    bl_idname="fluxfx.remove_emitter"
    bl_label="Remove Source Entry"
    bl_description="Stop using this additional source; keep its scene object and existing smoke"
    bl_options={"REGISTER","UNDO"}
    index: IntProperty()

    def execute(self,context):
        entries=context.scene.fluxfx.extra_emitters
        if not 0<=self.index<len(entries):return {"CANCELLED"}
        entries.remove(self.index);runtime.redraw()
        return {"FINISHED"}


class FLUXFX_OT_add_collider(bpy.types.Operator):
    bl_idname="fluxfx.add_collider"
    bl_label="Add Static Collider"
    bl_options={"REGISTER","UNDO"}
    shape: EnumProperty(items=[("SPHERE","Sphere",""),("BOX","Box","")])

    def execute(self,context):
        try: obj=create_collider(context.scene,self.shape)
        except ValueError as exc:
            self.report({"ERROR"},str(exc));return {"CANCELLED"}
        runtime.pause()
        for selected in context.selected_objects:selected.select_set(False)
        obj.select_set(True);context.view_layer.objects.active=obj
        self.report({"INFO"},"Position collider, then press Reset")
        runtime.redraw()
        return {"FINISHED"}


class FLUXFX_OT_mesh_collider(bpy.types.Operator):
    bl_idname="fluxfx.add_mesh_collider"
    bl_label="Use Selected Mesh"
    bl_description="Add the selected closed mesh as a static SDF collider; Reset to build"
    bl_options={"REGISTER","UNDO"}

    def execute(self,context):
        from uuid import uuid4
        obj=context.active_object;p=context.scene.fluxfx
        if obj is None or obj.type!='MESH':
            self.report({'ERROR'},'Select a closed Mesh object first');return {'CANCELLED'}
        if len(p.colliders)>=8:
            self.report({'ERROR'},'Maximum eight collider entries');return {'CANCELLED'}
        create_domain(context.scene);runtime.pause()
        entry=p.colliders.add();entry.name=uuid4().hex;entry.shape='MESH';entry.collider_object=obj
        self.report({'INFO'},'Disable Moving colliders, then Reset to build mesh collisions')
        runtime.redraw();return {'FINISHED'}


class FLUXFX_OT_remove_collider(bpy.types.Operator):
    bl_idname="fluxfx.remove_collider"
    bl_label="Remove Collider Entry"
    bl_description="Keep the scene object; press Reset to rebuild collision boundaries"
    bl_options={"REGISTER","UNDO"}
    index: IntProperty()

    def execute(self,context):
        entries=context.scene.fluxfx.colliders
        if not 0<=self.index<len(entries):return {"CANCELLED"}
        runtime.pause();entries.remove(self.index);runtime.redraw()
        return {"FINISHED"}


class FLUXFX_OT_diagnostics(bpy.types.Operator):
    bl_idname = "fluxfx.diagnostics"
    bl_label = "Run GPU Diagnostics"
    bl_description = "Report device capabilities and verify R32F 3D image writes with readback"

    def execute(self, context):
        report = collect(run_probe=True)
        text = bpy.data.texts.get("FluxFX Diagnostics.json") or bpy.data.texts.new("FluxFX Diagnostics.json")
        text.clear()
        text.write(json.dumps(report, indent=2))
        print(text.as_string())
        level = "INFO" if report["status"] == "READY" else "WARNING"
        self.report({level}, f"{report['status']} — see Text Editor: FluxFX Diagnostics.json")
        return {"FINISHED"}


class FLUXFX_OT_control(bpy.types.Operator):
    bl_idname = "fluxfx.control"
    bl_label = "FluxFX Preview"
    action: EnumProperty(items=[(s, s.title(), "") for s in ("RESET", "STEP", "PLAY", "PAUSE", "RELEASE", "MEASURE")])

    def execute(self, context):
        try:
            if self.action == "RESET":
                runtime.initialize(context.scene)
            elif self.action == "STEP":
                additional_history = runtime.STATE.additional_history
                history = runtime.STATE.emission_history
                runtime.pause()
                runtime.STATE.emission_history = history
                runtime.STATE.additional_history = additional_history
                runtime.step(context.scene)
            elif self.action == "PLAY":
                runtime.start(context.scene)
            elif self.action == "PAUSE":
                runtime.pause()
            elif self.action == "MEASURE":
                report = runtime.measure_projection(context.scene)
                text = bpy.data.texts.get("FluxFX Projection.json") or bpy.data.texts.new("FluxFX Projection.json")
                text.clear()
                text.write(json.dumps(report, indent=2))
                self.report({"INFO"}, f"Divergence RMS: {report['rms_before']:.4g} → {report['rms_after']:.4g}")
            elif self.action == "RELEASE":
                runtime.shutdown()
        except Exception as exc:
            runtime.pause()
            runtime.STATE.error = str(exc)
            traceback.print_exc()
            self.report({"ERROR"}, str(exc)[:250])
            return {"CANCELLED"}
        return {"FINISHED"}


class FLUXFX_OT_cache(bpy.types.Operator):
    bl_idname = "fluxfx.cache"
    bl_label = "FluxFX Bake / Cache"
    action: EnumProperty(items=[(s,s.title(),"") for s in ("BAKE","CANCEL","LOAD","RELEASE")])

    def execute(self,context):
        try:
            if self.action=="BAKE": cache.start_bake(context.scene)
            elif self.action=="CANCEL": cache.stop_bake()
            elif self.action=="LOAD": cache.load_cache(context.scene)
            elif self.action=="RELEASE": cache.shutdown()
            runtime.redraw()
        except Exception as exc:
            cache.STATE.message=str(exc)
            self.report({'ERROR'},str(exc)[:250]); return {'CANCELLED'}
        return {'FINISHED'}


class FLUXFX_OT_native_probe(bpy.types.Operator):
    bl_idname = "fluxfx.native_probe"
    bl_label = "Test Native Metal Core"
    bl_description = "Run the P1.0 compiled buffer/kernel test and save its report in the Text Editor"

    def execute(self, context):
        from ..native import run_probe
        try:
            report=run_probe()
            report['blender']=bpy.app.version_string
            context.scene.fluxfx.native_status=f"{report['status']} · {report['device']} · {report['mismatches']} mismatches"
        except Exception as exc:
            report=dict(status='ERROR',error=str(exc))
            context.scene.fluxfx.native_status=str(exc)
        text=bpy.data.texts.get('FluxFX Native Core.json') or bpy.data.texts.new('FluxFX Native Core.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},context.scene.fluxfx.native_status)
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_native_resources(bpy.types.Operator):
    bl_idname="fluxfx.native_resources"
    bl_label="Test Resource Layer"
    action: EnumProperty(items=[('TEST','Test','Allocate, dispatch and retain the arena'),('RELEASE','Release','Release native arena')],default='TEST')

    def execute(self,context):
        if self.action=='RELEASE':
            native_runtime.shutdown();return {'FINISHED'}
        try:
            report=native_runtime.test(context.scene)
        except Exception as exc:
            native_runtime.shutdown();self.report({'ERROR'},str(exc));return {'CANCELLED'}
        text=bpy.data.texts.get('FluxFX Native Resources.json') or bpy.data.texts.new('FluxFX Native Resources.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'},f"{report['status']} · native arena ready")
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_native_bricks(bpy.types.Operator):
    bl_idname="fluxfx.native_bricks"
    bl_label="Test Sparse Brick Pool"
    bl_description="Verify active bricks and neighbor IDs for 8 and 16 voxel bricks; report in Text Editor"

    def execute(self,context):
        from ..native import BrickPool
        report=dict(status='PASS',pools=[])
        try:
            for side,capacity in ((8,128),(16,16)):
                with BrickPool(side,capacity,context.scene.fluxfx.native_budget_mb*2**20) as pool:
                    pool.activate_box(0,0,0,32//side,32//side,32//side)
                    result=pool.probe()
                    report['pools'].append(dict(resources=pool.stats(),probe=result))
                    if result['status']!='PASS':report['status']='FAIL'
        except Exception as exc:
            report.update(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Native Bricks.json') or bpy.data.texts.new('FluxFX Native Bricks.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},
                    report.get('error',report['status']+' · sparse brick test'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_regions(bpy.types.Operator):
    bl_idname="fluxfx.regions"
    bl_label="Show Active Bricks"
    action: EnumProperty(items=[('START','Show','Update topology preview at 10 Hz'),('STOP','Hide','Release the pool and overlay')],default='START')
    def execute(self,context):
        if self.action=='STOP':regions.shutdown();return {'FINISHED'}
        try:regions.start(context.scene)
        except Exception as exc:
            regions.shutdown();self.report({'ERROR'},str(exc));return {'CANCELLED'}
        return {'FINISHED'}


class FLUXFX_OT_transport(bpy.types.Operator):
    bl_idname="fluxfx.transport_compare"
    bl_label="Compare Sparse Density"
    bl_description="Run eight 128-cubed density steps through sparse and dense Metal paths; save report and density slice"
    def execute(self,context):
        from array import array
        from ..native import compare_transport
        try:
            report=compare_transport(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            values=array('f');values.frombytes(report.pop('density'))
            report['status']='PASS' if report['max_error']<=1e-6 and abs(report['sparse_mass']-report['initial_mass'])/report['initial_mass']<=1e-6 else 'FAIL'
            n=report['resolution'];plane=values[(n//2)*n*n:(n//2+1)*n*n]
            image=bpy.data.images.get('FluxFX Sparse Density')
            if image is None:image=bpy.data.images.new('FluxFX Sparse Density',width=n,height=n,float_buffer=True)
            else:image.scale(n,n)
            image.pixels.foreach_set([channel for value in plane for channel in (value,value,value,1.)]);image.update()
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Sparse Transport.json') or bpy.data.texts.new('FluxFX Sparse Transport.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · density comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_sparse_mac(bpy.types.Operator):
    bl_idname="fluxfx.sparse_mac_compare"
    bl_label="Compare Sparse Velocity"
    bl_description="Run three 64-cubed MAC velocity steps through sparse and dense native paths"
    def execute(self,context):
        from ..native import compare_mac
        try:
            report=compare_mac(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            report.pop('faces')
            report['status']='PASS' if report['max_error']<=1e-6 and report['padding_error']==0 else 'FAIL'
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Sparse MAC.json') or bpy.data.texts.new('FluxFX Sparse MAC.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · MAC comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_sparse_projection(bpy.types.Operator):
    bl_idname="fluxfx.sparse_projection_compare"
    bl_label="Compare Sparse Pressure"
    bl_description="Compare fixed-region sparse and dense divergence and Jacobi projection at 64 cubed"
    def execute(self,context):
        from ..native import compare_projection
        try:
            report=compare_projection(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            for key in ('faces','pressure','before','after'):report.pop(key)
            passed=(report['max_error']<=1e-6 and report['pressure_error']<=1e-6
                    and report['padding_error']==0 and report['wall_error']==0
                    and report['after_rms']<report['before_rms']
                    and abs(report['after_rms']-report['residual_rms'])<=1e-6)
            report['status']='PASS' if passed else 'FAIL'
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Sparse Pressure.json') or bpy.data.texts.new('FluxFX Sparse Pressure.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · pressure comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_sparse_multigrid(bpy.types.Operator):
    bl_idname="fluxfx.sparse_multigrid_compare"
    bl_label="Compare Sparse Multigrid"
    bl_description="Compare four geometric V-cycles on matching sparse and dense pressure regions"
    def execute(self,context):
        from ..native import compare_multigrid
        try:
            report=compare_multigrid(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            for key in ('faces','pressure','before','after'):report.pop(key)
            passed=(report['max_error']<=1e-6 and report['pressure_error']<=1e-6
                    and report['padding_error']==0 and report['wall_error']==0
                    and report['after_rms']<.1*report['before_rms']
                    and abs(report['after_rms']-report['residual_rms'])<=1e-6)
            report['status']='PASS' if passed else 'FAIL'
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Sparse Multigrid.json') or bpy.data.texts.new('FluxFX Sparse Multigrid.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · multigrid comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_coupled(bpy.types.Operator):
    bl_idname="fluxfx.coupled_compare"
    bl_label="Compare Coupled Engine"
    bl_description="Compare three coupled steps with identical fixed pressure regions; not unrestricted dense equivalence"
    def execute(self,context):
        from ..native import compare_coupled
        try:
            report=compare_coupled(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            for key in ('density','faces','pressure','before','after'):report.pop(key)
            passed=(max(report['max_error'],report['density_error'],report['pressure_error'],report['divergence_error'])<=1e-6
                    and report['padding_error']==0 and report['wall_error']==0)
            report['status']='PASS' if passed else 'FAIL'
            report['validation_scope']='matched fixed-region implementation only'
            report['unrestricted_dense_equivalence']='not established by this diagnostic'
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Coupled Engine.json') or bpy.data.texts.new('FluxFX Coupled Engine.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · matched-region coupled comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_global_coverage(bpy.types.Operator):
    bl_idname="fluxfx.global_coverage_compare"
    bl_label="Compare Global Coverage"
    bl_description="Conservative full-domain fallback versus unrestricted dense; allocates all bricks"
    def execute(self,context):
        from ..native import compare_global_coupled
        try:
            report=compare_global_coupled(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            for key in ('density','faces','pressure','before','after'):report.pop(key)
            passed=(max(report['max_error'],report['density_error'],report['pressure_error'],report['divergence_error'])<=1e-6
                    and report['padding_error']==0 and report['wall_error']==0)
            report['status']='PASS' if passed else 'FAIL'
            report['validation_scope']='global-support native equivalence; all bricks allocated'
            report['sparse_efficiency_gate']=False
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Global Coverage.json') or bpy.data.texts.new('FluxFX Global Coverage.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · global coverage comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_hybrid(bpy.types.Operator):
    bl_idname="fluxfx.hybrid_compare"
    bl_label="Compare Hybrid Density"
    bl_description="Fixed sparse density with full-domain pressure and velocity; diagnostic only"
    def execute(self,context):
        from ..native import compare_hybrid_coupled
        try:
            report=compare_hybrid_coupled(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            for key in ('density','faces','pressure','before','after'):report.pop(key)
            passed=(max(report['max_error'],report['density_error'],report['pressure_error'],report['divergence_error'])<=1e-6
                    and report['padding_error']==0 and report['wall_error']==0)
            report['status']='PASS' if passed else 'FAIL'
            report['validation_scope']='fixed sparse density; global dense pressure and velocity'
            report['sparse_efficiency_gate']=False
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Hybrid Density.json') or bpy.data.texts.new('FluxFX Hybrid Density.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · hybrid density comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_adaptive(bpy.types.Operator):
    bl_idname="fluxfx.adaptive_compare"
    bl_label="Compare Adaptive Density"
    bl_description="Grow density bricks safely with global pressure and velocity; diagnostic only"
    def execute(self,context):
        from ..native import compare_adaptive_coupled
        try:
            report=compare_adaptive_coupled(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            for key in ('density','faces','pressure','before','after'):report.pop(key)
            passed=(max(report['max_error'],report['density_error'],report['pressure_error'],report['divergence_error'])<=1e-6
                    and report['padding_error']==0 and report['wall_error']==0)
            report['status']='PASS' if passed else 'FAIL'
            report['validation_scope']='grow-only density; full-domain preflight and global velocity/pressure'
            report['sparse_efficiency_gate']=False
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Adaptive Density.json') or bpy.data.texts.new('FluxFX Adaptive Density.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · adaptive density comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_OT_capacity(bpy.types.Operator):
    bl_idname="fluxfx.capacity_compare"
    bl_label="Compare Density Capacity"
    bl_description="Independent density buffers with reusable capacity; diagnostic only"
    def execute(self,context):
        from ..native import compare_capacity_coupled
        try:
            report=compare_capacity_coupled(budget_bytes=context.scene.fluxfx.native_budget_mb*2**20)
            for key in ('density','faces','pressure','before','after'):report.pop(key)
            passed=(max(report['max_error'],report['density_error'],report['pressure_error'],report['divergence_error'])<=1e-6
                    and report['padding_error']==0 and report['wall_error']==0)
            report['status']='PASS' if passed else 'FAIL'
            report['validation_scope']='independent density capacity; global velocity/pressure'
            report['sparse_efficiency_gate']=False
        except Exception as exc:report=dict(status='ERROR',error=str(exc))
        text=bpy.data.texts.get('FluxFX Density Capacity.json') or bpy.data.texts.new('FluxFX Density Capacity.json')
        text.clear();text.write(json.dumps(report,indent=2))
        self.report({'INFO'} if report['status']=='PASS' else {'ERROR'},report.get('error',report['status']+' · density capacity comparison'))
        return {'FINISHED'} if report['status']=='PASS' else {'CANCELLED'}


class FLUXFX_PT_main(bpy.types.Panel):
    bl_label = f"FluxFX · {VERSION_LABEL}"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "FluxFX"

    def draw(self, context):
        layout = self.layout
        props = context.scene.fluxfx
        state = runtime.STATE
        header, native_body = layout.panel("fluxfx_native",default_closed=True)
        header.label(text="Native core · P1.8")
        if native_body:
            native_body.prop(props,"native_budget_mb")
            for name in ('sparse_grid','sparse_capacity','sparse_linger','sparse_halo','sparse_speed_margin'):
                native_body.prop(props,name)
            native_body.operator('fluxfx.regions')
            if regions.pool is not None:native_body.operator('fluxfx.regions',text='Hide Active Bricks').action='STOP'
            native_body.label(text=regions.message[:90])
            native_body.label(text='Cyan: required · orange: retained')
            native_body.operator("fluxfx.capacity_compare")
            native_body.operator("fluxfx.adaptive_compare")
            native_body.operator("fluxfx.hybrid_compare")
            native_body.operator("fluxfx.global_coverage_compare")
            native_body.operator("fluxfx.coupled_compare")
            native_body.operator("fluxfx.sparse_multigrid_compare")
            native_body.operator("fluxfx.sparse_projection_compare")
            native_body.operator("fluxfx.sparse_mac_compare")
            native_body.operator("fluxfx.transport_compare")
            native_body.operator("fluxfx.native_bricks")
            native_body.operator("fluxfx.native_resources")
            if native_runtime.context is not None:
                info=native_runtime.context.stats()
                native_body.label(text=f"Arena: {info['resident_bytes']/2**20:.0f} MiB · used {info['used_bytes']/2**20:.2f} MiB")
                native_body.operator("fluxfx.native_resources",text="Release Native Arena").action='RELEASE'
            native_body.operator("fluxfx.native_probe")
            native_body.label(text=props.native_status[:80])
            native_body.label(text="Compute diagnostic · report in Text Editor")
        header, body = layout.panel("fluxfx_cache",default_closed=False)
        header.label(text="Bake and cache playback")
        if body:
            cs=cache.STATE
            if cs.job:
                body.label(text=f"Bake progress: {cs.progress:.0%}")
                body.operator("fluxfx.cache",text="Cancel Bake").action="CANCEL"
            else:
                body.prop(props,"cache_directory")
                row=body.row(align=True);row.prop(props,"cache_start");row.prop(props,"cache_end")
                body.prop(props,"cache_start_empty")
                body.prop(props,"cache_animated")
                body.prop(props,"cache_compress")
                body.label(text="Direct keys · sampled each frame" if props.cache_animated else "Fixed current inputs · animation not sampled")
                body.label(text="First frame is initial state · uses scene FPS")
                try: body.label(text=f"Max disk estimate: {cache.storage_estimate(context.scene)/2**20:.1f} MiB")
                except ValueError as exc: body.label(text=str(exc),icon='ERROR')
                body.operator("fluxfx.cache",text="Bake New Cache").action="BAKE"
                body.prop(props,"cache_path")
                body.prop(props,"cache_memory_mb")
                body.prop(props,"cache_prefetch")
                row=body.row(align=True)
                row.operator("fluxfx.cache",text="Load Cache").action="LOAD"
                row.operator("fluxfx.cache",text="Release Cache").action="RELEASE"
            if cs.message: body.label(text=cs.message[:90])
            if cs.reader:
                body.label(text="Scrub or play the Blender timeline")
                body.label(text=f"Last frame CPU work: {cs.load_ms:.1f} ms")
                if cs.memory:
                    body.label(text=f"Frame pool: {cs.memory.used_bytes/2**20:.1f} MiB · {len(cs.memory.entries)} frames")
                    body.label(text=f"Last prefetch: {cs.prefetch_ms:.1f} ms")
        if cache.STATE.job:
            return
        layout.label(text="Thermal flow · closed box")
        layout.operator("fluxfx.diagnostics", icon="SYSTEM")
        layout.prop(props, "domain_object")
        layout.operator("fluxfx.create_domain", icon="CUBE")
        header, body = layout.panel("fluxfx_setup", default_closed=True)
        header.label(text="Grid and initial state · reset on change")
        if body:
            body.enabled = not state.running
            for name in ("resolution", "time_step", "rise_speed", "swirl", "initial_temperature", "pressure_solver"):
                body.prop(props, name)
        header, body = layout.panel("fluxfx_combustion", default_closed=True)
        header.label(text="Combustion · fuel and fire")
        if body:
            body.prop(props,"combustion_enabled")
            body.operator("fluxfx.fire_preset")
            for name in ("ignition_temperature","burn_rate","heat_yield","smoke_yield"):
                body.prop(props,name)
            body.label(text="Heat must reach ignition to burn fuel")
        header, body = layout.panel("fluxfx_source", default_closed=False)
        header.label(text="Primary source · live controls")
        if body:
            body.prop(props, "emission_enabled")
            body.prop(props, "source_mode")
            if props.source_mode == "OBJECT":
                body.prop(props, "emitter_object")
                body.label(text="Move with G · size with S")
            else:
                body.prop(props, "source_center")
                body.prop(props, "source_radius")
            body.operator("fluxfx.create_emitter", icon="EMPTY_AXIS")
            body.prop(props,"density_mode");body.prop(props,"source_profile")
            body.prop(props,"source_rate",text="Target density" if props.density_mode=="TARGET" else "Density source /s")
            for name in ("fuel_source_rate", "heat_source_rate", "emission_velocity", "velocity_coupling", "motion_inheritance", "motion_speed_limit", "continuous_trails"):
                body.prop(props, name)
        header, body = layout.panel("fluxfx_additional", default_closed=False)
        header.label(text=f"Additional emitters · {len(props.extra_emitters)}/7")
        if body:
            for index,entry in enumerate(props.extra_emitters):
                box=body.box();row=box.row(align=True)
                row.prop(entry,"expanded",text="",icon="TRIA_DOWN" if entry.expanded else "TRIA_RIGHT",emboss=False)
                row.prop(entry,"emission_enabled",text="")
                row.prop(entry,"emitter_object",text="")
                row.operator("fluxfx.remove_emitter",text="",icon="X").index=index
                if entry.expanded:
                    controls=box.column();controls.enabled=entry.emission_enabled
                    controls.prop(entry,"density_mode");controls.prop(entry,"source_profile")
                    controls.prop(entry,"source_rate",text="Target density" if entry.density_mode=="TARGET" else "Density source /s")
                    for name in ("fuel_source_rate", "heat_source_rate","emission_velocity","velocity_coupling",
                                 "motion_inheritance","motion_speed_limit","continuous_trails"):
                        controls.prop(entry,name)
            row=body.row();row.enabled=len(props.extra_emitters)<7
            row.operator("fluxfx.add_emitter",icon="ADD")
        has_solids = any(entry.enabled for entry in props.colliders)
        header, body = layout.panel("fluxfx_colliders", default_closed=False)
        header.label(text=f"Colliders · {len(props.colliders)}/8")
        if body:
            body.label(text="Position with G/R/S, then Reset")
            body.label(text="Thickness: at least 2 grid cells")
            for index,entry in enumerate(props.colliders):
                box=body.box();row=box.row(align=True)
                row.prop(entry,"enabled",text="")
                row.prop(entry,"collider_object",text="")
                row.operator("fluxfx.remove_collider",text="",icon="X").index=index
                box.prop(entry,"shape")
            row=body.row(align=True);row.enabled=len(props.colliders)<8
            row.operator("fluxfx.add_collider",text="Add Sphere").shape="SPHERE"
            row.operator("fluxfx.add_collider",text="Add Box").shape="BOX"
            row=body.row();row.enabled=len(props.colliders)<8
            row.operator("fluxfx.add_mesh_collider")
            if any(e.enabled and e.shape=='MESH' for e in props.colliders):
                body.label(text="Closed mesh · static · edits require Reset")
                if state.solver and state.solver.solids:
                    for report in state.solver.solids.mesh_reports:
                        body.label(text=f"SDF: {report['occupied_cells']} cells · {report['build_seconds']:.2f}s")
                        for warning in report['warnings']:body.label(text=warning,icon='INFO')
            if has_solids:
                body.prop(props,"moving_colliders")
                body.label(text="Moving walls · Jacobi · fixed size" if props.moving_colliders else "Voxel walls · Detailed transport supported")
                if props.moving_colliders: body.label(text="Fast drags trail objects · speed capped")
                body.prop(props,"pressure_iterations")
        header, body = layout.panel("fluxfx_turbulence",default_closed=True)
        header.label(text="Turbulence · evolving scales")
        if body:
            for name in ('turbulence_strength','turbulence_scale','turbulence_speed','turbulence_seed','turbulence_octaves','turbulence_limit','turbulence_mask'):
                body.prop(props,name)
            if props.turbulence_mask!='ALL':body.prop(props,'turbulence_threshold')
            body.label(text="Scales below 4 cells are filtered out")
        header, body = layout.panel("fluxfx_flow", default_closed=True)
        header.label(text="Flow · live controls")
        if body:
            transport=body.column()
            transport.prop(props,"scalar_advection");transport.prop(props,"velocity_advection")
            for name in ("vorticity_strength", "vorticity_limit", "dissipation", "cooling", "thermal_lift", "density_weight"):
                body.prop(props, name)
            is_mg = not props.moving_colliders and props.pressure_solver in ("MULTIGRID","AUTO")
            body.prop(props, "pressure_cycles" if is_mg else "pressure_iterations")
        row = layout.row(align=True)
        for action in ("RESET", "STEP", "PAUSE" if state.running else "PLAY"):
            row.operator("fluxfx.control", text=action.title()).action = action
        if state.collider_motion_report and props.moving_colliders:
            layout.label(text=f"Collider tracking gap: {state.collider_motion_report['remaining_metres']*1000:.1f} mm")
        layout.prop(props, "playback_budget_ms")
        layout.prop(props, "adaptive_dt")
        if props.adaptive_dt:
            layout.prop(props, "cfl_target")
        layout.prop(props, "show_preview")
        layout.prop(props, "preview_mode")
        layout.prop(props, "preview_channel")
        cached_channels=cache.STATE.reader.meta['channels'] if cache.STATE.reader else ()
        if props.preview_channel=="COLLISION" and 'COLLISION' not in cached_channels and (state.solver is None or state.solver.solids is None):
            layout.label(text="Add a collider and Reset for this view",icon="INFO")
        if props.preview_channel in {"FUEL","FLAME"} and props.preview_channel not in cached_channels and (state.solver is None or state.solver.combustion is None):
            layout.label(text="Enable combustion and Reset for this view",icon="INFO")
        if props.preview_mode == "SLICE":
            layout.prop(props, "slice_y")
        else:
            layout.prop(props, "ray_steps")
        layout.prop(props, "exposure")
        if props.preview_mode == "SCENE":
            layout.label(text="Scene overlay · no object occlusion")
            if state.scene_preview and state.scene_preview.warning:
                layout.label(text=state.scene_preview.warning, icon="INFO")
        else:
            layout.label(text="Orbit viewport to rotate volume" if props.preview_mode == "VOLUME" else "Slice: X horizontal, Z up; 1 m domain")
        if state.solver is not None and state.scene == context.scene:
            layout.label(text=f"Step {state.solver.steps} · t = {state.solver.time:.3f} s")
            field_bytes = state.solver.allocated_bytes + state.timestep_controller.allocated_bytes + 4
            layout.label(text=f"Fields: {field_bytes / 2**20:.1f} MiB")
            layout.label(text=f"Completed step: {state.submit_ms:.2f} ms")
            if state.playback_report:
                playback = state.playback_report
                layout.label(text=f"Playback: {playback['speed']:.2f}× · lag {playback['lag_ms']:.0f} ms")
                layout.label(text=f"Callback: {playback['callback_ms']:.1f} ms · {playback['substeps']} steps")
                if playback['dropped_seconds'] > 0:
                    layout.label(text=f"Skipped wall time: {playback['dropped_seconds']:.2f} s", icon="INFO")
            if state.timestep_report:
                report = state.timestep_report
                layout.label(text=f"dt: {report['dt']:.6f} s · {report['mode'].lower()}")
                if report['mode'] == 'ADAPTIVE':
                    layout.label(text=f"Estimated CFL: {report['estimated_courant']:.3f}")
            measure = layout.row()
            measure.enabled = state.solver.steps > 0
            measure.operator("fluxfx.control", text="Measure Divergence").action = "MEASURE"
            if state.projection_report:
                report = state.projection_report
                layout.label(text=f"RMS: {report['rms_before']:.3g} → {report['rms_after']:.3g}")
                ratio = report['ratio']
                if ratio is not None:
                    budget = f"{report['v_cycles']} V-cycles" if report.get('v_cycles') else f"{report['iterations']} iterations"
                    layout.label(text=f"Remaining: {ratio:.1%} · {budget}")
                    if ratio > 0.1:
                        layout.label(text="Increase pressure budget", icon="INFO")
            layout.operator("fluxfx.control", text="Release GPU Preview").action = "RELEASE"
        if state.error:
            box = layout.box()
            box.label(text="Preview stopped — check console", icon="ERROR")
            box.label(text=state.error[:70])
        layout.label(text="Approximate projection · bounded step")


CLASSES = (FluxFXEmitterProperties, FluxFXColliderProperties, FluxFXProperties, FLUXFX_OT_fire_preset, FLUXFX_OT_add_collider, FLUXFX_OT_mesh_collider, FLUXFX_OT_remove_collider, FLUXFX_OT_domain, FLUXFX_OT_emitter, FLUXFX_OT_add_emitter, FLUXFX_OT_remove_emitter, FLUXFX_OT_diagnostics, FLUXFX_OT_control, FLUXFX_OT_cache, FLUXFX_OT_native_probe, FLUXFX_OT_native_resources, FLUXFX_OT_native_bricks, FLUXFX_OT_regions, FLUXFX_OT_transport, FLUXFX_OT_sparse_mac, FLUXFX_OT_sparse_projection, FLUXFX_OT_sparse_multigrid, FLUXFX_OT_coupled, FLUXFX_OT_global_coverage, FLUXFX_OT_hybrid, FLUXFX_OT_adaptive, FLUXFX_OT_capacity, FLUXFX_PT_main)


def register():
    if bpy.app.version < (5, 3, 0):
        raise RuntimeError("FluxFX P0 requires Blender 5.3 or newer")
    if hasattr(bpy.types.Scene, "fluxfx"):
        return
    registered = []
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            registered.append(cls)
        bpy.types.Scene.fluxfx = PointerProperty(type=FluxFXProperties)
        bpy.app.handlers.load_pre.append(runtime.before_load)
        bpy.app.handlers.undo_pre.append(runtime.before_undo)
        bpy.app.handlers.redo_pre.append(runtime.before_undo)
        bpy.app.handlers.frame_change_post.append(cache.frame_changed)
    except Exception:
        for cls in reversed(registered):
            bpy.utils.unregister_class(cls)
        raise


def unregister():
    runtime.shutdown()
    for handlers, callback in ((bpy.app.handlers.load_pre, runtime.before_load),
                               (bpy.app.handlers.undo_pre, runtime.before_undo),
                               (bpy.app.handlers.redo_pre, runtime.before_undo),
                               (bpy.app.handlers.frame_change_post, cache.frame_changed)):
        if callback in handlers:
            handlers.remove(callback)
    if hasattr(bpy.types.Scene, "fluxfx"):
        del bpy.types.Scene.fluxfx
    for cls in reversed(CLASSES):
        if "bl_rna" in cls.__dict__:
            bpy.utils.unregister_class(cls)
