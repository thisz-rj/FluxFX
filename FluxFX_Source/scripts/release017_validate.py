"""Synchronous graphical regression suite; run UI timer validation separately."""
from pathlib import Path
import json,runpy,traceback
ROOT=Path(__file__).resolve().parents[1]
def run_suite():
    dest=ROOT/'test-results/release017-validation.json'
    report={'status':'RUNNING','suites':{}}
    try:
        for name in ('motion_detail','pressure','multigrid_operators','detail','multiple','motion','emitter','timestep','interactive'):
            result=runpy.run_path(str(ROOT/'scripts'/f'{name}_validate.py'))['run_suite']()
            assert result['status']=='PASS',(name,result)
            report['suites'][name]=result
            dest.write_text(json.dumps(report,indent=2))
        report['status']='PASS'
    except Exception as exc:report['status']='FAIL';report['error']=repr(exc);report['traceback']=traceback.format_exc();raise
    finally:dest.write_text(json.dumps(report,indent=2))
    return report
if __name__=='__main__':run_suite()
