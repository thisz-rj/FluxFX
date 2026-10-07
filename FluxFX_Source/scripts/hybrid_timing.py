"""Graphical Blender timing: one warmup, five paired samples per brick size."""
from pathlib import Path
import json,statistics
from fluxfx.native import compare_hybrid_coupled
root=Path(__file__).resolve().parents[1]
rows=[]
for side in (8,16):
 samples=[]
 for repeat in range(6):
  r=compare_hybrid_coupled(128,side,8,8)
  for key in ('density','faces','pressure','before','after'):r.pop(key)
  assert max(r[k] for k in ('max_error','density_error','pressure_error','divergence_error'))<=1e-6
  if repeat:samples.append(r)
 rows.append(dict(side=side,samples=samples,median_hybrid_gpu_ms=statistics.median(r['sparse_gpu_ms'] for r in samples),median_dense_gpu_ms=statistics.median(r['dense_gpu_ms'] for r in samples)))
(root/'test-results/hybrid-timing.json').write_text(json.dumps(dict(status='PASS',warmup=1,repeats=5,rows=rows),indent=2))
print('HYBRID_TIMING PASS')
