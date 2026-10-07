"""Conservative global support, preserving localized seed and emission schedule."""
from pathlib import Path
import json,traceback
import numpy as np
from fluxfx.native import compare_global_coupled,compare_coupled,fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'scripts/coupled_validate.py'
ns=dict(__file__=str(p),__name__='global_reference')
package=compare_global_coupled.__module__.split('.native')[0]
exec(compile(p.read_text().split('\nreport=dict(status=')[0].replace('from '+'fluxfx.','from '+package+'.'),str(p),'exec'),ns)
unpack,reference=ns['unpack'],ns['reference']
report=dict(status='RUNNING',tests=[],benchmarks=[],truncation_controls=[],gates=dict(native_error=1e-6,cpu_error=1e-4))
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
  for mode in (1,2,3):
   for schedule in (0,1,2):
    r=compare_global_coupled(32,side,3,4,mode,schedule);out=unpack(r);ref=reference(32,3,4,mode,schedule,global_support=True)
    prefix=f'{side}_{mode}_{schedule}'
    error=max(float(np.max(np.abs(a-b))) for a,b in zip(out[0]+list(out[1:]),ref[0]+list(ref[1:])))
    check(prefix+'_cpu',error<=1e-4)
    check(prefix+'_dense',max(r[k] for k in ('max_error','pressure_error','density_error','divergence_error'))<=1e-6)
    check(prefix+'_global',r['global_support']==1 and r['dense_full']==1 and r['solve_cells']==32**3 and r['active_bricks']==(32//side)**3)
    check(prefix+'_mass',abs(r['sparse_mass']-r['dense_mass'])<=1e-5)
    check(prefix+'_walls_padding',r['wall_error']==0 and r['padding_error']==0)
 for kw in ({'steps':0},{'steps':17},{'cycles':0},{'cycles':17},{'schedule':3},{'resolution':31},{'side':4},{'budget_bytes':0}):rejects('invalid_'+str(kw),lambda:compare_global_coupled(**kw))
 rejects('budget',lambda:compare_global_coupled(128,budget_bytes=40*2**20))
 check('failure_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 for n in (64,128):
  old=compare_coupled(n,8,8,8,1,1,dense_full=True);unpack(old)
  check(f'{n}_negative_control',old['max_error']>1e-4 and old['density_error']>1e-4)
  report['truncation_controls'].append(old)
  for side in (8,16):
   r=compare_global_coupled(n,side,8,8,1,1);out=unpack(r)
   check(f'{n}_{side}_global_equivalence',max(r[k] for k in ('max_error','pressure_error','density_error','divergence_error'))<=1e-6)
   check(f'{n}_{side}_residual_identity',abs(r['after_rms']-r['residual_rms'])<=1e-6)
   check(f'{n}_{side}_finite',np.all(np.isfinite(out[1])) and np.min(out[1])>=0)
   r['density_occupancy']=float(np.count_nonzero(out[1]>1e-6)/n**3)
   report['benchmarks'].append(r)
 check('all_resources_released',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
 report.update(status='PASS',global_support_equivalence=True,sparse_efficiency_gate=False)
except Exception:report.update(status='FAIL',error=traceback.format_exc())
(ROOT/'test-results/global-coverage-validation.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_GLOBAL_COVERAGE',report['status'],len(report['tests']))
if report['status']=='FAIL':print(report['error'])
