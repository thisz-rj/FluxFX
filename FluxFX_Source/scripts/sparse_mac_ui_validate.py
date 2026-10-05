"""Graphical Blender sparse MAC operator and resource cleanup check."""
from pathlib import Path
import json
import bpy
from fluxfx.native import fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
assert bpy.ops.fluxfx.sparse_mac_compare()=={'FINISHED'}
r=json.loads(bpy.data.texts['FluxFX Sparse MAC.json'].as_string())
assert r['status']=='PASS' and r['max_error']<=1e-6 and r['padding_error']==0
assert fluxfx_core.resource_status()['owned_buffer_bytes']==baseline
(ROOT/'test-results/sparse-mac-ui-validation.json').write_text(json.dumps(dict(status='PASS',report=r,owned_bytes_after=baseline),indent=2))
print('FLUXFX_SPARSE_MAC_UI PASS')
