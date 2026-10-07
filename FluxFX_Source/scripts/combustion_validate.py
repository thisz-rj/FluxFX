"""Run inside graphical Blender: analytic burn, transport, sources and checkpoints."""
from pathlib import Path
from dataclasses import replace
from math import prod,isfinite
import json,traceback,tempfile
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.combustion import react
from fluxfx.physics.emission import Source,Emission
from fluxfx.physics.collision import primitive
from fluxfx.physics.collider_motion import MotionPath
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.checkpoint import save_checkpoint,load_checkpoint,advance_fixed
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    report={'status':'RUNNING','tests':[]};solvers=[]
    def check(name,condition,**details):
        assert condition,(name,details)
        report['tests'].append(dict(name=name,status='PASS',**details))
    def make(settings,colliders=()):
        s=DenseProjectedSmoke(GridSpec((16,)*3),settings,colliders=colliders);solvers.append(s);s.reset(seed=False);return s
    def read(s):return s.device.read(s.combustion.fuel,s.grid.shape)
    base=PressureSettings(combustion_enabled=True,source_rate=0,heat_source_rate=0,fuel_source_rate=0,
        velocity=(0,0,0),angular_speed=0,thermal_lift=0,density_weight=0,cooling=0,dissipation=0)
    try:
        for transport in ('SEMI_LAGRANGIAN','MACCORMACK'):
            s=make(replace(base,scalar_advection=transport))
            s.combustion.fuel=s.device.texture(s.grid.shape,[1.]*4096)
            s.upload_temperature([149.]*4096);s.step(.025)
            check(transport+'_cold_fuel_does_not_burn',max(abs(v-1) for v in read(s))<1e-6)
            s.upload_temperature([200.]*4096);s.step(.025)
            burned=react(1,200,.025,150,4)
            check(transport+'_analytic_fuel',max(abs(v-(1-burned)) for v in read(s))<2e-6)
            check(transport+'_heat_yield',max(abs(v-(200+burned*600)) for v in s.read_temperature())<1e-4)
            check(transport+'_smoke_yield',max(abs(v-burned) for v in s.read_density())<2e-6)
            flame=s.device.read(s.combustion.flame,s.grid.shape)
            check(transport+'_flame_is_burn_rate',max(abs(v-burned/.025) for v in flame)<1e-5)
            s.update_settings(replace(s.settings,burn_rate=0));s.step(.025)
            check(transport+'_zero_rate_stops_flame',max(s.device.read(s.combustion.flame,s.grid.shape))==0)
        s=make(base)
        src=Source((.5,)*3,.3,0,0,Emission((.5,)*3),profile='SOLID',fuel_rate=2)
        s.step(.025,sources=[src,src])
        check('multiple_fuel_sources_add',abs(max(read(s))-.1)<1e-6)
        s.update_settings(replace(base,fuel_source_rate=2,source_center=(.5,)*3,source_radius=.3,source_profile='SOLID'))
        s.reset(seed=False);s.step(.025)
        check('primary_fuel_source',abs(max(read(s))-.05)<1e-6)
        s.update_settings(replace(s.settings,fuel_source_rate=0));s.step(.025)
        check('emission_off_preserves_cold_fuel',abs(max(read(s))-.05)<1e-6)
        # Replay and resume retain pressure guess and fuel fields.
        settings=replace(base,fuel_source_rate=2,heat_source_rate=1000,source_rate=0,thermal_lift=.005,ignition_temperature=10)
        a=make(settings);b=make(settings)
        advance_fixed(a,12,.01);advance_fixed(b,12,.01)
        check('fixed_input_replay',max(abs(x-y) for x,y in zip(a.read_density(),b.read_density()))<1e-6)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fire.npz';save_checkpoint(a,path);c=load_checkpoint(path);solvers.append(c)
            check('checkpoint_clock_and_fuel',c.time==a.time and c.steps==a.steps and read(c)==read(a))
            advance_fixed(a,8,.01);advance_fixed(c,8,.01)
            err=max(abs(x-y) for x,y in zip(a.read_temperature(),c.read_temperature()))
            check('checkpoint_resume_matches',err<1e-4,error=err)
        for moving in (False,True):
            obstacle=primitive('BOX',(.5,)*3,(.15,)*3)
            s=make(replace(settings,moving_colliders=moving,source_center=(.5,)*3,source_radius=.3),[obstacle])
            for _ in range(10):s.step(.02)
            if moving:
                path=MotionPath((obstacle,),(primitive('BOX',(.6,.5,.5),(.15,)*3),),.2)
                s.move_colliders(path.at(.02),.02);s.step(.02)
            mask=s.device.read(s.solids.mask,s.grid.shape)
            check(('moving' if moving else 'static')+'_fuel_and_flame_exclusion',all(f==0 and b==0 for f,b,m in zip(read(s),s.device.read(s.combustion.flame,s.grid.shape),mask) if m))
        check('all_fields_finite',all(isfinite(v) for s in solvers for field in (s.read_density(),s.read_temperature(),read(s)) for v in field))
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        for s in solvers:s.close()
        (ROOT/'test-results/combustion-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_COMBUSTION',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
