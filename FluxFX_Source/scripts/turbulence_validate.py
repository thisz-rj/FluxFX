"""Graphical GPU force oracles, masks, bounds and checkpoint reproduction."""
from pathlib import Path
from dataclasses import replace
from math import sin,sqrt,isfinite
import json,traceback,tempfile
from fluxfx.physics.config import GridSpec
from fluxfx.physics.pressure import PressureSettings
from fluxfx.physics.turbulence import spectrum
from fluxfx.backend.projected import DenseProjectedSmoke
from fluxfx.backend.mac import FACE_OFFSETS
from fluxfx.backend.checkpoint import save_checkpoint,load_checkpoint,advance_fixed
from fluxfx.backend.timestep import AdaptiveTimestep
ROOT=Path(__file__).resolve().parents[1]

def run_suite():
    report={'status':'RUNNING','tests':[]};solvers=[]
    def check(name,value,**extra):
        assert value,(name,extra)
        report['tests'].append(dict(name=name,status='PASS',**extra))
    def make(s):
        a=DenseProjectedSmoke(GridSpec((16,)*3),s);a.reset(seed=False);solvers.append(a);return a
    base=PressureSettings(source_rate=0,heat_source_rate=0,initial_temperature=0,thermal_lift=0,density_weight=0,
        turbulence_strength=2,turbulence_scale=1,turbulence_mask='ALL',turbulence_limit=.3)
    try:
        s=make(base);s.time=.25;dt=.02
        fields=s.turbulence.apply(s,s._velocity,dt);waves=spectrum(s.grid,base);error=0;peak=0
        for axis,(tex,shape) in enumerate(zip(fields,s.grid.face_shapes)):
            values=s.device.read(tex,shape)
            for i,value in enumerate(values):
                p=[(v+o)/16 for v,o in zip((i%shape[0],i//shape[0]%shape[1],i//(shape[0]*shape[1])),FACE_OFFSETS[axis])]
                f=[0.,0.,0.]
                for j in range(12):
                    k=waves[j*8:j*8+4];a=waves[j*8+4:j*8+8]
                    phase=sum(x*y for x,y in zip(k,p))+k[3]+s.time*base.turbulence_speed*a[3]
                    for c in range(3):f[c]+=2*a[c]*sin(phase)
                length=sqrt(sum(v*v for v in f));expected=dt*f[axis]*min(1,.3/max(length,1e-12))
                error=max(error,abs(value-expected));peak=max(peak,abs(value))
        check('gpu_matches_transverse_force',error<2e-6,error=error)
        check('acceleration_component_bound',peak<=dt*.3+1e-6)
        original=[s.device.read(t,sh) for t,sh in zip(fields,s.grid.face_shapes)]
        s.time+=.4;changed=s.turbulence.apply(s,s._velocity,dt)
        check('evolves_with_simulation_time',any(abs(a-b)>1e-5 for old,t,sh in zip(original,changed,s.grid.face_shapes) for a,b in zip(old,s.device.read(t,sh))))
        for mode in ('DENSITY','HEAT'):
            s.update_settings(replace(base,turbulence_mask=mode));out=s.turbulence.apply(s,s._velocity,dt)
            check(mode+'_empty_mask_zero',all(v==0 for t,sh in zip(out,s.grid.face_shapes) for v in s.device.read(t,sh)))
        s.update_settings(replace(base,turbulence_scale=.1));out=s.turbulence.apply(s,s._velocity,dt)
        check('unresolved_modes_zero',all(v==0 for t,sh in zip(out,s.grid.face_shapes) for v in s.device.read(t,sh)))
        a=make(base);b=make(base);advance_fixed(a,8,.02);advance_fixed(b,8,.02)
        check('seeded_replay',a.read_velocity()==b.read_velocity())
        a.update_settings(replace(base,turbulence_seed=19));a.step(.02);b.step(.02)
        check('seed_changes_flow',a.read_velocity()!=b.read_velocity())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'turbulence.npz';save_checkpoint(b,path);c=load_checkpoint(path);solvers.append(c)
            advance_fixed(b,4,.02);advance_fixed(c,4,.02)
            check('checkpoint_preserves_phase_and_flow',max(abs(x-y) for a,b in zip(b.read_velocity(),c.read_velocity()) for x,y in zip(a,b))<1e-5)
        ctl=AdaptiveTimestep(s.grid,s.device)
        try:
            s.update_settings(replace(base,turbulence_strength=0));off=ctl.select(s,.03,.75)
            s.update_settings(base);on=ctl.select(s,.03,.75)
            check('adaptive_bound_includes_forcing',on['acceleration_rate_bound']>off['acceleration_rate_bound'])
        finally:ctl.close()
        zero=make(replace(base,turbulence_strength=0));zero.step(.02)
        check('disabled_allocates_no_scratch',zero.turbulence.allocated_bytes==0)
        check('finite_projected_fields',all(isfinite(v) for s in solvers for f in s.read_velocity() for v in f))
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        for s in solvers:s.close()
        (ROOT/'test-results/turbulence-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_TURBULENCE',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run_suite()
