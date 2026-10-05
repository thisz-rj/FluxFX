"""Graphical native region contract checks and Metal topology integration."""
from pathlib import Path
import json,traceback
from fluxfx.native import BrickPool,fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
report=dict(status='RUNNING',tests=[])
def check(name,condition):
 assert condition,name
 report['tests'].append(name)
def rejects(name,fn):
 try:fn()
 except (ValueError,RuntimeError,OverflowError,TypeError):check(name,True)
 else:raise AssertionError(name)
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
try:
 with BrickPool(8,128,2**20) as p:
  source=(.3,.3,.3,.01,0.,0.,0.)
  p.update_regions([source],8,.1,3,0)
  check('one_source_brick',len(p.snapshot())==1 and p.lookup(2,2,2)>=0)
  check('gpu_initial',p.probe()['status']=='PASS')
  p.update_regions([],8,.1,3,0);check('retained_step_one',p.snapshot()[0][4]==1)
  p.update_regions([],8,.1,3,0);check('retained_step_two',p.snapshot()[0][4]==2)
  p.update_regions([],8,.1,3,0);check('removed_third_step',p.snapshot()==[])
  moving=(*source[:4],3.,0.,0.)
  p.update_regions([moving],8,.1,3,0)
  check('predicted_positive_velocity',p.lookup(4,2,2)>=0 and p.lookup(1,2,2)==-1)
  before=p.snapshot()
  rejects('exhaustion',lambda:p.update_regions([(.5,.5,.5,2.,0.,0.,0.)],8,.1,3,0))
  check('atomic_topology_and_ages',p.snapshot()==before)
  for kwargs in ({'dt':float('nan')},{'dt':0},{'linger':0},{'halo':-1},{'grid':65},{'grid':-2**32}):
   rejects('invalid_'+str(kwargs),lambda:p.update_regions([source],**kwargs))
  rejects('nonfinite_source',lambda:p.update_regions([(float('nan'),)*7]))
  check('invalid_preserves_topology',p.snapshot()==before)
  p.update_regions([],8,.1,1,0)
  p.update_regions([(.3,.3,.3,.01,-3.,0.,0.)],8,.1,3,0)
  check('negative_velocity_clipped',p.lookup(0,2,2)>=0 and p.lookup(3,2,2)==-1)
  check('gpu_negative_velocity',p.probe()['status']=='PASS')
  p.update_regions([],8,.1,1,0)
  p.update_regions([source,source],8,.1,3,1)
  check('duplicate_sources_and_halo',len(p.snapshot())==27)
  check('compact_unique_slots',len({r[3] for r in p.snapshot()})==27)
  check('gpu_halo',p.probe()['status']=='PASS')
  p.update_regions([],8,.1,3,1)
  p.update_regions([source],8,.1,3,1)
  check('reactivation_resets_ages',all(r[4]==0 for r in p.snapshot()))
  p.update_regions([],8,.1,1,0)
  check('gpu_empty_after_expiry',p.probe()['status']=='PASS')
 check('cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 report['status']='PASS'
except Exception:report.update(status='FAIL',error=traceback.format_exc())
(ROOT/'test-results/regions-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_REGIONS',report['status'],len(report['tests']))
