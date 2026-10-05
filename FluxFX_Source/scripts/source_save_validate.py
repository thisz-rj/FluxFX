"""Background Blender check: source collection and object links survive save/load."""
from pathlib import Path
import sys,json,tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import bpy,fluxfx
from fluxfx.blender.collider import create_collider,collider_snapshot
from fluxfx.blender.emitter import create_emitter,create_additional_emitter
fluxfx.register()
scene=bpy.context.scene
create_emitter(scene)
scene.fluxfx.scalar_advection="MACCORMACK"
scene.fluxfx.velocity_advection="SEMI_LAGRANGIAN"
scene.fluxfx.playback_budget_ms=17
scene.fluxfx.native_budget_mb=32
scene.fluxfx.sparse_grid=256;scene.fluxfx.sparse_capacity=1024
scene.fluxfx.sparse_linger=5;scene.fluxfx.sparse_halo=2;scene.fluxfx.sparse_speed_margin=1.5
scene.fluxfx.cache_compress=True
scene.fluxfx.cache_memory_mb=192;scene.fluxfx.cache_prefetch=False
scene.fluxfx.cache_directory='/tmp/fluxfx-save-check/'
scene.fluxfx.cache_path='/tmp/fluxfx-save-check/fluxfx-bake-example/'
scene.fluxfx.cache_start=11;scene.fluxfx.cache_end=32;scene.fluxfx.cache_start_empty=False
scene.fluxfx.moving_colliders=True
scene.fluxfx.combustion_enabled=True
scene.fluxfx.fuel_source_rate=2.5
scene.fluxfx.burn_rate=3
scene.fluxfx.preview_channel="FLAME"
scene.fluxfx.vorticity_strength=4
scene.fluxfx.vorticity_limit=2
turbulence_values=dict(turbulence_strength=2, turbulence_scale=.75, turbulence_speed=.5,
    turbulence_seed=47, turbulence_octaves=4, turbulence_limit=1,
    turbulence_mask="HEAT", turbulence_threshold=125)
for name,value in turbulence_values.items():setattr(scene.fluxfx,name,value)
scene.fluxfx.density_mode="TARGET"
scene.fluxfx.source_profile="SOLID"
for i in range(3):
    obj=create_additional_emitter(scene)
    entry=scene.fluxfx.extra_emitters[-1]
    obj.location.x=i*.1
    entry.fuel_source_rate=i+.5
    entry.source_rate=i+1
    entry.density_mode="TARGET" if i==0 else "RATE"
    entry.source_profile="SOLID" if i==0 else "SOFT"
    entry.heat_source_rate=-10*i
    entry.emission_velocity=(i,0,1)
    entry.motion_inheritance=.5
    entry.emission_enabled=i!=1
sphere=create_collider(scene,'SPHERE');box=create_collider(scene,'BOX')
box.location=(.2,0,.1);box.rotation_euler.z=.4
scene.fluxfx.colliders[0].enabled=False
bpy.context.view_layer.update()
solid_snapshot=collider_snapshot(scene)
solid_names=[c.name for c in scene.fluxfx.colliders]
names=[e.name for e in scene.fluxfx.extra_emitters]
with tempfile.TemporaryDirectory(prefix='fluxfx-save-') as temp:
    path=str(Path(temp)/'sources.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    entries=bpy.context.scene.fluxfx.extra_emitters
    assert len(entries)==3
    settings=bpy.context.scene.fluxfx
    assert settings.playback_budget_ms==17
    assert settings.native_budget_mb==32
    assert (settings.sparse_grid,settings.sparse_capacity,settings.sparse_linger,settings.sparse_halo,settings.sparse_speed_margin)==(256,1024,5,2,1.5)
    assert settings.cache_compress
    assert settings.cache_memory_mb==192 and not settings.cache_prefetch
    assert settings.cache_directory=='/tmp/fluxfx-save-check/' and settings.cache_path=='/tmp/fluxfx-save-check/fluxfx-bake-example/'
    assert (settings.cache_start,settings.cache_end,settings.cache_start_empty)==(11,32,False)
    assert settings.combustion_enabled and settings.fuel_source_rate==2.5 and settings.burn_rate==3 and settings.preview_channel=="FLAME"
    assert all(getattr(settings,name)==value for name,value in turbulence_values.items())
    assert settings.moving_colliders
    assert len(settings.colliders)==2 and not settings.colliders[0].enabled
    assert [c.name for c in settings.colliders]==solid_names
    assert collider_snapshot(bpy.context.scene)==solid_snapshot
    assert all(c.collider_object.parent==settings.domain_object for c in settings.colliders)
    assert settings.velocity_advection=="SEMI_LAGRANGIAN"
    assert settings.scalar_advection=="MACCORMACK" and settings.vorticity_strength==4 and settings.vorticity_limit==2
    assert settings.density_mode=="TARGET" and settings.source_profile=="SOLID"
    assert [e.name for e in entries]==names
    for i,entry in enumerate(entries):
        assert entry.density_mode==("TARGET" if i==0 else "RATE")
        assert entry.source_profile==("SOLID" if i==0 else "SOFT")
        assert entry.fuel_source_rate==i+.5
        assert entry.source_rate==i+1 and entry.heat_source_rate==-10*i
        assert tuple(entry.emission_velocity)==(i,0,1) and entry.motion_inheritance==.5
        assert entry.emission_enabled==(i!=1)
        assert entry.emitter_object in list(bpy.context.scene.objects)
        assert entry.emitter_object.parent==bpy.context.scene.fluxfx.domain_object
    report={'status':'PASS','checks':['collection_count','stable_source_ids','per_source_settings','object_links_and_parenting','detail_and_calibration_settings','playback_budget','cache_controls_and_paths','cache_compression_saved','frame_memory_controls_saved','native_budget_saved','sparse_region_controls','combustion_controls','turbulence_controls','moving_collider_mode','collider_bindings_transforms_and_enabled_state']}
    (ROOT/'test-results/source-save-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_SAVE_VALIDATION',report)
fluxfx.unregister()
