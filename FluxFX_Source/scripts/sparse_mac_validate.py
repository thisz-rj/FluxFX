"""Graphical sparse MAC ownership, interpolation, self-advection and references."""
from pathlib import Path
import json,traceback
import numpy as np
from fluxfx.native import compare_mac,fluxfx_core
from fluxfx.backend.device import BlenderGPUDevice
from fluxfx.backend.mac import VELOCITY_NAMES,FACE_OFFSETS,AXIS_MASKS,FACE_CONSTANTS
ROOT=Path(__file__).resolve().parents[1]

def positions(n,axis):
 shape=[n,n,n];shape[2-axis]+=1
 z,y,x=np.indices(shape,dtype=np.float64)
 return [x+FACE_OFFSETS[axis][0],y+FACE_OFFSETS[axis][1],z+FACE_OFFSETS[axis][2]]
def seed(n,mode):
 fields=[]
 for axis in range(3):
  p=positions(n,axis)
  if mode==2:v=np.full(p[0].shape,(.25,-.125,.0625)[axis])
  elif mode==3:v=np.full(p[0].shape,(.35,-.2,.1)[axis])
  else:v=.1*(axis+1)+.2*(p[(axis+1)%3]/n-.5)-.3*(p[(axis+2)%3]/n-.5)
  if mode in (0,3):v=v*np.logical_and.reduce([(q>=n*.25)&(q<n*.75) for q in p])
  fields.append(v.astype(np.float32))
 return fields

def sample(field,q):
 q=[np.clip(c,0,size-1) for c,size in zip(q,field.shape[::-1])]
 lo=[np.floor(c).astype(int) for c in q];f=[c-b for c,b in zip(q,lo)]
 out=np.zeros(q[0].shape)
 for z in (0,1):
  for y in (0,1):
   for x in (0,1):
    ix=np.minimum(lo[0]+x,field.shape[2]-1);iy=np.minimum(lo[1]+y,field.shape[1]-1);iz=np.minimum(lo[2]+z,field.shape[0]-1)
    out+=field[iz,iy,ix]*(f[0] if x else 1-f[0])*(f[1] if y else 1-f[1])*(f[2] if z else 1-f[2])
 return out

def velocity(fields,p):
 return [sample(field,[q-o for q,o in zip(p,offset)]) for field,offset in zip(fields,FACE_OFFSETS)]
def cpu_reference(n,mode,steps):
 fields=seed(n,mode)
 for _ in range(steps):
  outputs=[]
  for axis in range(3):
   p=positions(n,axis);v=velocity(fields,p);mid=[q-.5*u for q,u in zip(p,v)]
   v=velocity(fields,mid);departure=[q-u-o for q,u,o in zip(p,v,FACE_OFFSETS[axis])]
   outputs.append(sample(fields[axis],departure).astype(np.float32))
  fields=outputs
 return fields

def blender_reference(n,mode,steps):
 dev=BlenderGPUDevice();fields=seed(n,mode)
 textures=[dev.texture(f.shape[::-1],f.ravel().tolist(),nonnegative=False) for f in fields]
 backs=[dev.texture(f.shape[::-1],nonnegative=False) for f in fields]
 kernel=dev.kernel('transport_face.glsl',FACE_CONSTANTS+(("FLOAT","dt"),),sample_input=True,samplers=VELOCITY_NAMES,includes=('mac_sample.glsl',))
 # Domain extent N gives cell size 1, matching native velocities in voxels/step.
 for _ in range(steps):
  sources=dict(zip(VELOCITY_NAMES,textures))
  for axis in range(3):
   dev.dispatch(kernel,backs[axis],fields[axis].shape[::-1],{'domainExtent':(n,n,n),'cellCount':(n,n,n),'faceOffset':FACE_OFFSETS[axis],'axisMask':AXIS_MASKS[axis],'dt':1.},textures[axis],sources=sources)
  textures,backs=backs,textures
 return [np.asarray(dev.read(t,f.shape[::-1]),dtype=np.float32).reshape(f.shape) for t,f in zip(textures,fields)]

def unpack(r):
 n=r['resolution'];count=(n+1)*n*n;data=np.frombuffer(r.pop('faces'),dtype=np.float32)
 return [data[a*count:(a+1)*count].reshape(positions(n,a)[0].shape) for a in range(3)]
report=dict(status='RUNNING',tests=[],benchmarks=[],gates=dict(native_max_error=1e-6,independent_max_error=1e-4,padding_error=0))
def check(name,value):
 assert value,name
 report['tests'].append(name)
def rejects(name,fn):
 try:fn()
 except (RuntimeError,ValueError,OverflowError,TypeError):check(name,True)
 else:raise AssertionError(name)
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
try:
 for side in (8,16):
  for mode in range(4):
   for steps in (0,3):
    r=compare_mac(32,side,steps,mode);fields=unpack(r)
    reference=seed(32,mode) if steps==0 else cpu_reference(32,mode,steps)
    e=max(float(np.max(np.abs(a-b))) for a,b in zip(fields,reference))
    check(f'{side}_{mode}_{steps}_dense_match',r['max_error']<=1e-6)
    check(f'{side}_{mode}_{steps}_independent_reference',e<=1e-4)
    check(f'{side}_{mode}_{steps}_padding_untouched',r['padding_error']==0)
    check(f'{side}_{mode}_{steps}_finite',all(np.all(np.isfinite(a)) for a in fields))
    if mode in (1,2):check(f'{side}_{mode}_{steps}_unique_face_ownership',r['owned_faces']==3*32*32*33)
    if mode==2:check(f'{side}_{steps}_constant_preservation',all(np.max(np.abs(a-v))<=1e-6 for a,v in zip(fields,(.25,-.125,.0625))))
    if side==8 and mode==0 and steps==3:
     blender=blender_reference(32,mode,steps)
     report['blender_dense_max_error']=max(float(np.max(np.abs(a-b))) for a,b in zip(fields,blender))
     check('existing_Blender_MAC_shader',report['blender_dense_max_error']<=1e-4)
 for kwargs in ({'resolution':31},{'side':4},{'steps':-1},{'steps':9},{'mode':4},{'budget_bytes':0},{'budget_bytes':2**64}):
  rejects('invalid_'+str(kwargs),lambda:compare_mac(**kwargs))
 rejects('budget_failure',lambda:compare_mac(128,budget_bytes=2**20))
 rejects('second_engine_failure_cleanup',lambda:compare_mac(128,budget_bytes=20*2**20))
 check('failure_releases_memory',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 for n in (64,128):
  for side in (8,16):
   r=compare_mac(n,side,3,0);fields=unpack(r)
   check(f'{n}_{side}_sparse_match',r['max_error']<=1e-6 and r['padding_error']==0)
   if n==64:
    reference=cpu_reference(n,0,3)
    check(f'{n}_{side}_missing_brick_reference',max(float(np.max(np.abs(a-b))) for a,b in zip(fields,reference))<=1e-4)
   if n==128:check(f'{n}_{side}_memory_saving',r['sparse_bytes']<r['dense_bytes'])
   report['benchmarks'].append(r)
 check('all_resources_released',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 report['status']='PASS'
except Exception:report.update(status='FAIL',error=traceback.format_exc())
(ROOT/'test-results/sparse-mac-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_MAC',report['status'],len(report['tests']))
