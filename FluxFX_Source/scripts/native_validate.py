"""Run in graphical Blender; the native Metal device may be unavailable headless."""
from pathlib import Path
import json,sys,traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fluxfx.native import fluxfx_core as core

def run():
    report=dict(status='RUNNING',tests=[],probes=[])
    def check(name,value):
        assert value,name
        report['tests'].append(dict(name=name,status='PASS'))
    try:
        check('initial_buffer_ownership_zero',core.resource_status()['owned_buffer_bytes']==0)
        for opts in ({'count':0},{'count':-1},{'count':16777217},{'count':2**64+1},
                     {'count':1.5},{'repeats':0},{'repeats':33},{'seed':-1},{'seed':2**32}):
            try:core.run_probe(**opts)
            except (ValueError,OverflowError,TypeError):pass
            else:raise AssertionError('Invalid command accepted: '+str(opts))
        check('invalid_commands_rejected',True)
        for count in (1,7,257,4097,1048576,16777216):
            result=core.run_probe(count=count,repeats=3,seed=2**32-2)
            check(f'{count}_exact_kernel_output',result['status']=='PASS' and result['mismatches']==0)
            check(f'{count}_completed_timestamps',len(result['gpu_command_ms'])==3 and all(t is not None and t>=0 for t in result['gpu_command_ms']))
            check(f'{count}_resources_released',core.resource_status()['owned_buffer_bytes']==0)
            report['probes'].append(result)
        for _ in range(32):
            assert core.run_probe(count=65537,repeats=2)['status']=='PASS'
            assert core.resource_status()['owned_buffer_bytes']==0
        check('repeated_create_dispatch_destroy',True)
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    (ROOT/'test-results').mkdir(exist_ok=True)
    (ROOT/'test-results/native-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_NATIVE',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run()
