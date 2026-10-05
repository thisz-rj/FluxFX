"""One warmup and three paired capacity/legacy adaptive timing samples."""
from pathlib import Path
import json,statistics
from fluxfx.native import compare_capacity_coupled,compare_adaptive_coupled
ROOT=Path(__file__).resolve().parents[1]
rows=[]
for side in (8,16):
 samples=[]
 for repeat in range(4):
  pair={}
  for name,fn in (('capacity',compare_capacity_coupled),('legacy',compare_adaptive_coupled)):
   r=fn(128,side,8,8)
   for key in ('density','faces','pressure','before','after'):r.pop(key)
   assert max(r[k] for k in ('max_error','density_error','pressure_error','divergence_error'))<=1e-6
   pair[name]=r
  if repeat:samples.append(pair)
 rows.append(dict(side=side,samples=samples,medians={name:{key:statistics.median(pair[name][key] for pair in samples) for key in ('sparse_wall_ms','sparse_gpu_ms','dense_wall_ms','dense_gpu_ms')} for name in ('capacity','legacy')}))
(ROOT/'test-results/capacity-timing.json').write_text(json.dumps(dict(status='PASS',warmup=1,repeats=3,rows=rows),indent=2))
print('CAPACITY_TIMING PASS')
