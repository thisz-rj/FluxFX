"""Graphical multigrid validation against independent CPU V-cycles and Jacobi."""
from pathlib import Path
import json,traceback
import numpy as np
from fluxfx.native import compare_multigrid,compare_projection,fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
# Share only seed/layout helpers with the validated projection oracle.
helpers=dict(globals(),__file__=str(ROOT/'scripts/sparse_projection_validate.py'))
exec(compile((ROOT/'scripts/sparse_projection_validate.py').read_text().split("report=dict(status=")[0].replace("from "+"fluxfx.","from "+compare_multigrid.__module__.split(".native")[0]+"."),str(ROOT/'scripts/sparse_projection_validate.py'),'exec'),helpers)
mask,seed,unpack=helpers['mask'],helpers['seed'],helpers['unpack']
divergence=helpers['divergence']

def stencil(q):
 total=np.zeros_like(q);diag=np.full(q.shape,6.,np.float32)
 for a in range(3):
  lo=[slice(None)]*3;hi=lo.copy();lo[a]=slice(None,-1);hi[a]=slice(1,None)
  total[tuple(lo)]+=q[tuple(hi)];total[tuple(hi)]+=q[tuple(lo)]
  edge=[slice(None)]*3;edge[a]=0;diag[tuple(edge)]-=1;edge[a]=-1;diag[tuple(edge)]-=1
 return total,diag

def smooth(q,rhs,m,count):
 for _ in range(count):
  total,diag=stencil(q);q=((1-np.float32(2/3))*q+np.float32(2/3)*(total-rhs)/diag)*m
 return q

def prolong(q,n):
 z,y,x=np.indices((n,n,n),dtype=np.float64);pos=[(c+.5)*.5-.5 for c in (x,y,z)]
 lo=[np.floor(c).astype(int) for c in pos];f=[c-b for c,b in zip(pos,lo)];out=np.zeros((n,n,n),np.float64)
 for z in (0,1):
  for y in (0,1):
   for x in (0,1):
    out+=q[np.clip(lo[2]+z,0,len(q)-1),np.clip(lo[1]+y,0,len(q)-1),np.clip(lo[0]+x,0,len(q)-1)]*(f[0] if x else 1-f[0])*(f[1] if y else 1-f[1])*(f[2] if z else 1-f[2])
 return out.astype(np.float32)

def cycle(q,rhs,mode):
 n=len(q);m=mask(n,mode)
 if n==8:return smooth(q,rhs,m,128)
 q=smooth(q,rhs,m,4);total,diag=stencil(q);r=(rhs-(total-diag*q))*m
 # Block average restriction scaled by h_coarse^2/h_fine^2.
 nc=n//2;rc=4*r.reshape(nc,2,nc,2,nc,2).mean(axis=(1,3,5))*mask(nc,mode)
 qc=cycle(np.zeros_like(rc),rc,mode)
 q=(q+prolong(qc,n))*m
 return smooth(q,rhs,m,4)

def reference(n,mode,cycles):
 fields=seed(n,mode);m=mask(n,mode);rhs=divergence(fields,m);q=np.zeros_like(rhs)
 for _ in range(cycles):q=cycle(q,rhs,mode)
 out=[]
 for a,f in enumerate(fields):
  u=f.copy();sl=[slice(None)]*3;sl[2-a]=slice(1,-1);u[tuple(sl)]-=np.diff(q,axis=2-a);out.append(u)
 return out,q,rhs,divergence(out,m)

report=dict(status='RUNNING',tests=[],cases=[],benchmarks=[],gates=dict(reference_error=5e-5,native_error=1e-6,four_cycle_ratio=.1))
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
  for mode in range(5):
   last=None
   for cycles in (1,4):
    r=compare_multigrid(32,side,cycles,mode);out=unpack(r);ref=reference(32,mode,cycles)
    error=max(float(np.max(np.abs(a-b))) for a,b in zip(out[0]+list(out[1:]),ref[0]+list(ref[1:])))
    prefix=f'{side}_{mode}_{cycles}'
    check(prefix+'_cpu',error<=5e-5)
    check(prefix+'_dense',r['max_error']<=1e-6 and r['pressure_error']<=1e-6)
    check(prefix+'_boundaries',r['wall_error']==0 and r['padding_error']==0)
    check(prefix+'_residual',abs(r['after_rms']-r['residual_rms'])<=1e-6)
    check(prefix+'_hierarchy',r['levels']==3 and r['sparse_hierarchy_bytes']>0)
    if mode==3:check(prefix+'_zero',r['after_rms']==0)
    else:
     check(prefix+'_reduction',r['after_rms']<r['before_rms'])
     if cycles==4:check(prefix+'_four_cycle_gate',r['after_rms']<.1*r['before_rms'] and r['after_rms']<last)
    last=r['after_rms'];r['cpu_max_error']=error;report['cases'].append(r)
 r=compare_multigrid(64,8,4,1);out=unpack(r);ref=reference(64,1,4)
 check('missing_brick_cpu',max(float(np.max(np.abs(a-b))) for a,b in zip(out[0]+list(out[1:]),ref[0]+list(ref[1:])))<=5e-5)
 for kw in ({'cycles':0},{'cycles':17},{'cycles':-1},{'cycles':1.5},{'resolution':31},{'side':4},{'mode':5},{'budget_bytes':0}):rejects('invalid_'+str(kw),lambda:compare_multigrid(**kw))
 rejects('first_allocation_budget',lambda:compare_multigrid(128,budget_bytes=2**20))
 # Fits both finest engines, fails during coarse hierarchy construction.
 fine=compare_projection(64,8,0,1)
 rejects('hierarchy_budget_cleanup',lambda:compare_multigrid(64,8,4,1,budget_bytes=fine['dense_bytes']))
 check('failure_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 for n in (64,128):
  for side in (8,16):
   j=compare_projection(n,side,128,1);unpack(j)
   history=[]
   for cycles in (1,2,4,8):
    r=compare_multigrid(n,side,cycles,1);unpack(r);history.append(r)
    check(f'{n}_{side}_{cycles}_native',r['max_error']<=1e-6 and r['pressure_error']<=1e-6)
   check(f'{n}_{side}_convergence',all(b['after_rms']<a['after_rms'] for a,b in zip(history,history[1:])))
   check(f'{n}_{side}_beats_jacobi',history[2]['after_rms']<j['after_rms'])
   check(f'{n}_{side}_eight_cycle_gate',history[-1]['after_rms']<.1*j['before_rms'])
   if n==128:check(f'{n}_{side}_memory',history[-1]['sparse_bytes']<history[-1]['dense_bytes'])
   report['benchmarks'].append(dict(jacobi=j,multigrid=history))
 check('all_resources_released',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 report['status']='PASS'
except Exception:report.update(status='FAIL',error=traceback.format_exc())
(ROOT/'test-results/sparse-multigrid-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_MULTIGRID',report['status'],len(report['tests']))
if report['status']=='FAIL':print(report['error'])
