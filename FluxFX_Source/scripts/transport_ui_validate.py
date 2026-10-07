"""Graphical Blender operator check with the current add-on registered."""
from pathlib import Path
import json
import bpy
from fluxfx.native import fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
assert bpy.ops.fluxfx.transport_compare()=={'FINISHED'}
r=json.loads(bpy.data.texts['FluxFX Sparse Transport.json'].as_string())
assert r['status']=='PASS' and r['max_error']<=1e-6
image=bpy.data.images['FluxFX Sparse Density']
assert tuple(image.size)==(128,128) and max(image.pixels[:])==1.0
assert any(0<v<1 for v in image.pixels[:])
assert fluxfx_core.resource_status()['owned_buffer_bytes']==baseline
(ROOT/'test-results/transport-ui-validation.json').write_text(json.dumps(dict(status='PASS',report=r,image=list(image.size),owned_bytes_after=baseline),indent=2))
print('FLUXFX_TRANSPORT_UI PASS')
