"""Graphical operator report and owned-buffer cleanup check."""
from pathlib import Path
import json,bpy
from fluxfx.native import fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
assert bpy.ops.fluxfx.hybrid_compare()=={'FINISHED'}
r=json.loads(bpy.data.texts['FluxFX Hybrid Density.json'].as_string())
assert r['status']=='PASS' and r['density_error']<=1e-6 and r['divergence_error']<=1e-6
assert fluxfx_core.resource_status()['owned_buffer_bytes']==baseline
(ROOT/'test-results/hybrid-ui-validation.json').write_text(json.dumps(dict(status='PASS',report=r,owned_bytes_after=baseline),indent=2))
print('FLUXFX_HYBRID_UI PASS')
