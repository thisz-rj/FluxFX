"""Graphical operator report and owned-buffer cleanup check."""
from pathlib import Path
import json,bpy
from fluxfx.native import fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
assert bpy.ops.fluxfx.sparse_multigrid_compare()=={'FINISHED'}
r=json.loads(bpy.data.texts['FluxFX Sparse Multigrid.json'].as_string())
assert r['status']=='PASS' and r['after_rms']<r['before_rms']
assert fluxfx_core.resource_status()['owned_buffer_bytes']==baseline
(ROOT/'test-results/sparse-multigrid-ui-validation.json').write_text(json.dumps(dict(status='PASS',report=r,owned_bytes_after=baseline),indent=2))
print('FLUXFX_SPARSE_MULTIGRID_UI PASS')
