"""Graphical P1.4 correctness gates, independent references and benchmarks."""
from pathlib import Path
import json,traceback
import numpy as np
from fluxfx.native import compare_transport,fluxfx_core
from fluxfx.backend.device import BlenderGPUDevice
from fluxfx.backend.mac import VELOCITY_NAMES
ROOT=Path(__file__).resolve().parents[1]

def seed(n):
 a=np.zeros((n,n,n),dtype=np.float32);extent=n*7//16;lo=(n-extent)//2
 a[lo:lo+extent,lo:lo+extent,lo:lo+extent]=1
 return a

def cpu_reference(n,steps,delta):
 a=seed(n)
 # Separable trilinear interpolation for constant translation; independent NumPy oracle.
 for _ in range(steps):
  for axis,v in zip((2,1,0),delta):
   q=np.arange(n,dtype=np.float64)-v;lo=np.floor(q).astype(int);f=q-lo
   shape=[1,1,1];shape[axis]=n;f=f.reshape(shape)
   a=(np.take(a,np.clip(lo,0,n-1),axis=axis)*(1-f)+np.take(a,np.clip(lo+1,0,n-1),axis=axis)*f).astype(np.float32)
 return a

def blender_reference(n,steps,delta):
 device=BlenderGPUDevice();shape=(n,n,n)
 a=device.texture(shape,seed(n).ravel().tolist());b=device.texture(shape)
 velocity={}
 for axis,name in enumerate(VELOCITY_NAMES):
  face=list(shape);face[axis]+=1;tex=device.texture(tuple(face),nonnegative=False)
  tex.clear(format='FLOAT',value=(delta[axis]/n,));velocity[name]=tex
 kernel=device.kernel('transport_scalar.glsl',(('VEC3','domainExtent'),('VEC3','cellCount'),('FLOAT','dt')),
                       sample_input=True,samplers=VELOCITY_NAMES,includes=('mac_sample.glsl','closed_sample.glsl'))
 for _ in range(steps):
  device.dispatch(kernel,b,shape,{'domainExtent':(1.,1.,1.),'cellCount':shape,'dt':1.},a,sources=velocity)
  a,b=b,a
 return np.asarray(device.read(a,shape),dtype=np.float32).reshape(shape)

report=dict(status='RUNNING',tests=[],benchmarks=[],gates=dict(native_max_error=1e-6,reference_max_error=1e-4,interior_mass_relative_error=1e-6))
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
  for delta,steps in (((0,0,0),3),((1,-1,0),4),((.6,-.3,.2),8),((-.7,.25,-.4),8),((4,0,0),8)):
   r=compare_transport(32,side,steps,delta)
   a=np.frombuffer(r.pop('density'),dtype=np.float32).reshape((32,)*3)
   reference=cpu_reference(32,steps,delta)
   error=float(np.max(np.abs(a-reference)))
   check(f'{side}_{delta}_native_match',r['max_error']<=1e-6)
   check(f'{side}_{delta}_numpy_reference',error<=1e-4)
   check(f'{side}_{delta}_finite_bounded',np.all(np.isfinite(a)) and a.min()>=0 and a.max()<=1)
   if delta==(1,-1,0):
    expected=np.roll(seed(32),shift=(0,-4,4),axis=(0,1,2))
    check(f'{side}_analytic_integer_translation',np.array_equal(a,expected))
 for args in ((31,8,8,(0,0,0)),(32,4,8,(0,0,0)),(32,8,0,(0,0,0)),(32,8,33,(0,0,0)),(32,8,1,(float('nan'),0,0)),(32,8,1,(5,0,0))):
  rejects('invalid_'+str(args),lambda:compare_transport(*args))
 rejects('budget_exhaustion',lambda:compare_transport(128,budget_bytes=2**20))
 # Allocation failure after the sparse engine fits must also release it.
 rejects('dense_allocation_budget_cleanup',lambda:compare_transport(128,budget_bytes=8*2**20))
 check('failure_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 for n in (128,256):
  for side in (8,16):
   r=compare_transport(n,side,8,(.6,.2,.1))
   a=np.frombuffer(r.pop('density'),dtype=np.float32).reshape((n,)*3)
   check(f'{n}_{side}_native_numerical_gate',r['max_error']<=1e-6)
   check(f'{n}_{side}_mass_gate',abs(r['sparse_mass']-r['initial_mass'])/r['initial_mass']<=1e-6)
   check(f'{n}_{side}_memory_reduction',r['sparse_bytes']<r['dense_bytes'])
   if n==128 and side==8:
    ref=blender_reference(n,8,(.6,.2,.1));error=float(np.max(np.abs(a-ref)))
    r['blender_dense_max_error']=error
    check('existing_dense_shader_reference',error<=1e-4)
   report['benchmarks'].append(r)
 check('all_resources_released',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 report['status']='PASS'
except Exception:report.update(status='FAIL',error=traceback.format_exc())
(ROOT/'test-results/transport-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_TRANSPORT',report['status'],len(report['tests']))
