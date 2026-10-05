"""Compare solvers at a common residual gate; short repeated diagnostic timing."""
from pathlib import Path
import json,statistics
from fluxfx.native import compare_multigrid,compare_projection
ROOT=Path(__file__).resolve().parents[1]
def compact(r):
 for k in ('faces','pressure','before','after'):r.pop(k)
 return r
report=dict(status='RUNNING',target_ratio=.1,resolution=128,side=8,search=[],samples=[])
for iterations in (128,256,512,1024):
 r=compact(compare_projection(128,8,iterations,1));report['search'].append(r)
 if r['after_rms']<=.1*r['before_rms']:break
assert r['after_rms']<=.1*r['before_rms'],'Jacobi did not reach target in bounded search'
report['jacobi_iterations']=iterations
for trial in range(3):
 pair={}
 for method in (('multigrid','jacobi') if trial%2==0 else ('jacobi','multigrid')):
  r=compact(compare_multigrid(128,8,8,1) if method=='multigrid' else compare_projection(128,8,iterations,1))
  assert r['after_rms']<=.1*r['before_rms'] and r['max_error']<=1e-6
  pair[method]=r
 report['samples'].append(pair)
report['median_sparse_wall_ms']={method:statistics.median(s[method]['sparse_wall_ms'] for s in report['samples']) for method in ('multigrid','jacobi')}
report['status']='PASS'
(ROOT/'test-results/sparse-multigrid-benchmark.json').write_text(json.dumps(report,indent=2))
print('FLUXFX_MULTIGRID_BENCHMARK',report['status'],report['median_sparse_wall_ms'])
