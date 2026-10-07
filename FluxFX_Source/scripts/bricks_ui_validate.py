"""Graphical Blender operator test; FluxFX must already be registered."""
from pathlib import Path
import json
import bpy
from fluxfx.native import fluxfx_core
ROOT=Path(__file__).resolve().parents[1]
baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
result=bpy.ops.fluxfx.native_bricks()
report=json.loads(bpy.data.texts['FluxFX Native Bricks.json'].as_string())
assert result=={'FINISHED'} and report['status']=='PASS'
assert len(report['pools'])==2
assert all(p['probe']['mismatches']==0 for p in report['pools'])
assert fluxfx_core.resource_status()['owned_buffer_bytes']==baseline
(ROOT/'test-results').mkdir(exist_ok=True)
(ROOT/'test-results/bricks-ui-validation.json').write_text(json.dumps(
    dict(status='PASS',operator_report=report,owned_bytes_after=baseline),indent=2))
print('FLUXFX_BRICKS_UI PASS')
