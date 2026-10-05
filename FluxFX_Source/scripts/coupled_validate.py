"""Coupled native transport/source/projection validation and truncation audit."""
from pathlib import Path
import json,traceback
import numpy as np
from fluxfx.native import compare_coupled,fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
package=compare_coupled.__module__.split('.native')[0]
def helpers(name):
 p=ROOT/'scripts'/name;ns=dict(__file__=str(p),__name__='reference_helpers')
 text=p.read_text().split('\nreport=dict(status=')[0].replace('from '+'fluxfx.','from '+package+'.')
 exec(compile(text,str(p),'exec'),ns);return ns
mg=helpers('sparse_multigrid_validate.py');mac=helpers('sparse_mac_validate.py')
mask,seed,cycle=mg['mask'],mg['seed'],mg['cycle'];sample,velocity,positions=mac['sample'],mac['velocity'],mac['positions']
def source(n,step,schedule):
 z,y,x=np.indices((n,n,n),dtype=np.float64);cx=.5*n+(.05*n*np.sin(.5*step) if schedule==1 else 0.)
 radius=n/12;v=.1*np.maximum(0,1-((x+.5-cx)**2+(y+.5-.5*n)**2+(z+.5-.45*n)**2)/radius**2)
 if schedule==2 and step%2:v.fill(0)
 return v.astype(np.float32)
def reference(n,steps,cycles,mode,schedule,global_support=False):
 fields=seed(n,mode);solve_mode=0 if global_support else mode;m=mask(n,solve_mode);rho=np.zeros((n,n,n),np.float32)
 for step in range(steps):
  adv=[]
  for a,f in enumerate(fields):
   p=positions(n,a);v=velocity(fields,p);mid=[q-.5*u for q,u in zip(p,v)];v=velocity(fields,mid)
   off=[.5,.5,.5];off[a]=0
   u=sample(f,[q-vv-o for q,vv,o in zip(p,v,off)]).astype(np.float32)
   adj=np.zeros(u.shape,bool);sl=[slice(None)]*3;sl[2-a]=slice(None,-1);adj[tuple(sl)]|=m;sl[2-a]=slice(1,None);adj[tuple(sl)]|=m
   u*=adj;sl[2-a]=0;u[tuple(sl)]=0;sl[2-a]=-1;u[tuple(sl)]=0;adv.append(u)
  rhs=mg['divergence'](adv,m);q=np.zeros_like(rho)
  for _ in range(cycles):q=cycle(q,rhs,solve_mode)
  fields=[]
  for a,f in enumerate(adv):
   u=f.copy();sl=[slice(None)]*3;sl[2-a]=slice(1,-1);u[tuple(sl)]-=np.diff(q,axis=2-a);fields.append(u)
  rho=(rho+source(n,step,schedule))*m
  z,y,x=np.indices((n,n,n),dtype=np.float64);p=[x+.5,y+.5,z+.5];v=velocity(fields,p);mid=[c-.5*u for c,u in zip(p,v)];v=velocity(fields,mid)
  rho=(sample(rho,[c-u-.5 for c,u in zip(p,v)])*m).astype(np.float32)
 return fields,rho,q,mg['divergence'](fields,m)
def unpack(r):
 n=r['resolution'];rho=np.frombuffer(r.pop('density'),np.float32).reshape(n,n,n)
 f,q,b,a=mg['unpack'](r);return f,rho,q,a
report=dict(status='RUNNING',tests=[],benchmarks=[],unrestricted_comparisons=[],gates=dict(native_error=1e-6,cpu_error=1e-4,global_velocity_error=1e-4,global_density_error=1e-4))
def check(name,value):
 assert value,name
 report['tests'].append(name)
def rejects(name,fn):
 try:fn()
 except (ValueError,RuntimeError,OverflowError,TypeError):check(name,True)
 else:raise AssertionError(name)
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
try:
 for side in (8,16):
  for mode in (0,1,3):
   for schedule in (0,1,2):
    r=compare_coupled(32,side,3,4,mode,schedule);out=unpack(r);ref=reference(32,3,4,mode,schedule)
    err=max(float(np.max(np.abs(a-b))) for a,b in zip(out[0]+list(out[1:]),ref[0]+list(ref[1:])))
    prefix=f'{side}_{mode}_{schedule}'
    check(prefix+'_cpu',err<=1e-4)
    check(prefix+'_native',r['max_error']<=1e-6 and r['density_error']<=1e-6 and r['pressure_error']<=1e-6 and r['divergence_error']<=1e-6)
    check(prefix+'_mass',abs(r['sparse_mass']-r['dense_mass'])<=1e-5 and r['sparse_mass']>0)
    check(prefix+'_boundaries',r['padding_error']==0 and r['wall_error']==0)
    check(prefix+'_finite_positive',np.all(np.isfinite(out[1])) and np.min(out[1])>=0)
    if mode==3:check(prefix+'_zero_velocity_source_mass',max(float(np.max(np.abs(f))) for f in out[0])==0 and abs(r['sparse_mass']-r['injected_mass'])<1e-4)
 r=compare_coupled(64,8,3,4,1,1);out=unpack(r);ref=reference(64,3,4,1,1)
 check('missing_bricks_cpu',max(float(np.max(np.abs(a-b))) for a,b in zip(out[0]+list(out[1:]),ref[0]+list(ref[1:])))<=1e-4)
 for kw in ({'steps':0},{'steps':17},{'cycles':0},{'cycles':17},{'schedule':3},{'resolution':31},{'side':4},{'dense_full':1},{'budget_bytes':0}):rejects('invalid_'+str(kw),lambda:compare_coupled(**kw))
 rejects('budget_cleanup',lambda:compare_coupled(128,budget_bytes=40*2**20))
 check('failed_call_releases',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 for n in (64,128):
  for side in (8,16):
   r=compare_coupled(n,side,8,8,1,1);out=unpack(r)
   check(f'{n}_{side}_eight_steps',r['max_error']<=1e-6 and r['density_error']<=1e-6 and r['padding_error']==0)
   r['density_occupancy']=float(np.count_nonzero(out[1]>1e-6)/n**3)
   r['allocated_brick_occupancy']=r['active_bricks']/(n/side)**3
   report['benchmarks'].append(r)
  r=compare_coupled(n,8,8,8,1,1,dense_full=True);unpack(r)
  report['unrestricted_comparisons'].append(r)
 report['unrestricted_dense_gate']=all(r['max_error']<=1e-4 and r['density_error']<=1e-4 for r in report['unrestricted_comparisons'])
 report['milestone_status']='PASS' if report['unrestricted_dense_gate'] else 'OPEN: truncated pressure differs from unrestricted dense'
 check('all_resources_released',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 report['status']='PASS'
except Exception:report.update(status='FAIL',error=traceback.format_exc())
(ROOT/'test-results/coupled-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_COUPLED',report['status'],len(report['tests']))
if report['status']=='FAIL':print(report['error'])
