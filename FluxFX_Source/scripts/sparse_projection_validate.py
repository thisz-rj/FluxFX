"""Graphical P1.6 projection tests: independent NumPy and Blender references."""
from pathlib import Path
import json,traceback
import numpy as np
from fluxfx.native import compare_projection,fluxfx_core
ROOT=Path(__file__).resolve().parents[1]

def mask(n,mode):
 z,y,x=np.indices((n,n,n));m=np.ones((n,n,n),bool)
 if mode in (1,2):
  def box(lo,hi):return (x>=lo)&(y>=lo)&(z>=lo)&(x<hi)&(y<hi)&(z<hi)
  m=box(n//4,3*n//4) if mode==1 else box(n//8,3*n//8)|box(5*n//8,7*n//8)
 return m

def seed(n,mode):
 m=mask(n,mode);fields=[]
 z,y,x=np.indices((n,n,n));q=(np.cos(8*np.pi*(x+.5)/n)*np.cos(8*np.pi*(y+.5)/n)*np.cos(8*np.pi*(z+.5)/n)).astype(np.float32)
 for a in range(3):
  shape=[n,n,n];shape[2-a]+=1;z,y,x=np.indices(shape);pos=[x+.5,y+.5,z+.5];pos[a]-=.5
  u=(.2*(a+1)*np.sin(8*np.pi*pos[a]/n)+.1*np.cos(4*np.pi*pos[(a+1)%3]/n)).astype(np.float32)
  if mode==3:u.fill(0)
  if mode==4:
   u.fill(0);sl=[slice(None)]*3;sl[2-a]=slice(1,-1);u[tuple(sl)]=np.diff(q,axis=2-a)
  adj=np.zeros(shape,bool);sl=[slice(None)]*3;sl[2-a]=slice(0,-1);adj[tuple(sl)]|=m;sl[2-a]=slice(1,None);adj[tuple(sl)]|=m
  u*=adj;sl[2-a]=0;u[tuple(sl)]=0;sl[2-a]=-1;u[tuple(sl)]=0;fields.append(u)
 return fields

def divergence(fields,m):return sum(np.diff(f,axis=2-a) for a,f in enumerate(fields))*m

def cpu(n,mode,iterations):
 m=mask(n,mode);fields=seed(n,mode);rhs=divergence(fields,m);q=np.zeros_like(rhs);diag=np.full(q.shape,6.,dtype=np.float32)
 for axis in range(3):
  s=[slice(None)]*3;s[axis]=0;diag[tuple(s)]-=1;s[axis]=-1;diag[tuple(s)]-=1
 for _ in range(iterations):
  total=np.zeros_like(q)
  for axis in range(3):
   lo=[slice(None)]*3;hi=lo.copy();lo[axis]=slice(None,-1);hi[axis]=slice(1,None)
   total[tuple(lo)]+=q[tuple(hi)];total[tuple(hi)]+=q[tuple(lo)]
  q=((1-np.float32(2/3))*q+np.float32(2/3)*(total-rhs)/diag)*m
 out=[]
 for a,f in enumerate(fields):
  u=f.copy();s=[slice(None)]*3;s[2-a]=slice(1,-1);u[tuple(s)]-=np.diff(q,axis=2-a);out.append(u)
 return out,q,rhs,divergence(out,m)

def unpack(r):
 n=int(r['resolution']);count=(n+1)*n*n;data=np.frombuffer(r.pop('faces'),np.float32);fields=[]
 for a in range(3):
  shape=[n,n,n];shape[2-a]+=1;fields.append(data[a*count:(a+1)*count].reshape(shape))
 return fields,*[np.frombuffer(r.pop(k),np.float32).reshape(n,n,n) for k in ('pressure','before','after')]

def blender(n,iterations):
 from fluxfx.backend.device import BlenderGPUDevice
 from fluxfx.backend.pressure import PressureProjector
 from fluxfx.physics.config import GridSpec
 from fluxfx.physics.pressure import PressureSettings
 dev=BlenderGPUDevice();fields=seed(n,0)
 grid=GridSpec(shape=(n,n,n),extent=(n,n,n))
 settings=PressureSettings(pressure_iterations=iterations,pressure_cold_multiplier=1,pressure_relaxation=2/3,pressure_warm_start="IMPULSE")
 solver=PressureProjector(grid,settings,dev)
 inp=[dev.texture(f.shape[::-1],f.ravel().tolist(),nonnegative=False) for f in fields]
 out=[dev.texture(f.shape[::-1],nonnegative=False) for f in fields]
 solver.project(inp,out,.1)
 values=[np.asarray(dev.read(t,f.shape[::-1]),np.float32).reshape(f.shape) for t,f in zip(out,fields)]
 solver.close();return values

report=dict(status='RUNNING',tests=[],benchmarks=[],gates=dict(reference_max_error=2e-5,native_max_error=1e-6,divergence_ratio=.25,residual_agreement=1e-6))
def check(name,value):
 assert value,name
 report['tests'].append(name)
def rejects(name,fn):
 try:fn()
 except (ValueError,RuntimeError,TypeError,OverflowError):check(name,True)
 else:raise AssertionError(name)
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
try:
 for side in (8,16):
  for mode in range(5):
   for iterations in (0,64):
    r=compare_projection(32,side,iterations,mode);out=unpack(r);ref=cpu(32,mode,iterations)
    err=max(float(np.max(np.abs(a-b))) for a,b in zip(out[0]+list(out[1:]),ref[0]+list(ref[1:])))
    prefix=f'{side}_{mode}_{iterations}'
    check(prefix+'_independent',err<=2e-5)
    check(prefix+'_native',r['max_error']<=1e-6 and r['pressure_error']<=1e-6)
    check(prefix+'_wall_padding',r['wall_error']==0 and r['padding_error']==0)
    check(prefix+'_residual',abs(r['after_rms']-r['residual_rms'])<=1e-6)
    check(prefix+'_mask',r['solve_cells']==np.count_nonzero(mask(32,mode)))
    if iterations and mode!=3:check(prefix+'_divergence_reduction',r['after_rms']<.25*r['before_rms'])
    if iterations and mode!=3:check(prefix+'_energy',sum(float(np.sum(f.astype(np.float64)**2)) for f in out[0])<=sum(float(np.sum(f.astype(np.float64)**2)) for f in seed(32,mode)))
    if mode in (0,4):check(prefix+'_closed_rhs_compatible',abs(float(np.sum(out[2],dtype=np.float64)))<1e-3)
    if mode==3:check(prefix+'_zero',r['before_rms']==0 and r['after_rms']==0)
    if mode==4 and iterations:check(prefix+'_manufactured_gradient',max(float(np.max(np.abs(f))) for f in out[0])<1e-3)
 r=compare_projection(32,8,64,0);out=unpack(r);ref=blender(32,64)
 report['blender_max_error']=max(float(np.max(np.abs(a-b))) for a,b in zip(out[0],ref));check('Blender_dense_shader',report['blender_max_error']<=2e-5)
 r=compare_projection(64,8,64,1);out=unpack(r);ref=cpu(64,1,64)
 check('missing_bricks_independent',max(float(np.max(np.abs(a-b))) for a,b in zip(out[0]+list(out[1:]),ref[0]+list(ref[1:])))<=2e-5)
 # More iterations must lower residual for a fixed nonzero RHS.
 a=compare_projection(32,8,16,1);b=compare_projection(32,8,128,1)
 check('convergence',b['residual_rms']<a['residual_rms'])
 for kw in ({'resolution':31},{'side':4},{'iterations':-1},{'iterations':1025},{'mode':5},{'budget_bytes':0},{'budget_bytes':2**64}):
  rejects('invalid_'+str(kw),lambda:compare_projection(**kw))
 rejects('budget_before_allocation',lambda:compare_projection(128,budget_bytes=2**20))
 rejects('second_engine_budget_cleanup',lambda:compare_projection(128,budget_bytes=40*2**20))
 check('failure_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 for n in (64,128):
  for side in (8,16):
   r=compare_projection(n,side,128,1);unpack(r)
   check(f'{n}_{side}_native',r['max_error']<=1e-6 and r['pressure_error']<=1e-6)
   check(f'{n}_{side}_decrease',r['after_rms']<r['before_rms'])
   if n==128:check(f'{n}_{side}_memory',r['sparse_bytes']<r['dense_bytes'])
   report['benchmarks'].append(r)
 check('all_resources_released',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 report['status']='PASS'
except Exception:report.update(status='FAIL',error=traceback.format_exc())
(ROOT/'test-results/sparse-projection-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_PROJECTION',report['status'],len(report['tests']))
if report['status']=='FAIL':print(report['error'])
