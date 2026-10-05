"""Graphical native P1.1 resource checks; no fluid physics."""
from pathlib import Path
import gc,json,traceback,time
from fluxfx.native import Context,fluxfx_core
ROOT=Path(__file__).resolve().parents[1]

def run():
    report=dict(status='RUNNING',tests=[],timings=[])
    contexts=[]
    def check(name,condition):
        assert condition,name
        report['tests'].append(dict(name=name,status='PASS'))
    def rejects(name,call):
        try:call()
        except (ValueError,RuntimeError,OverflowError,TypeError):check(name,True)
        else:raise AssertionError(name)
    try:
        baseline=fluxfx_core.resource_status()['owned_buffer_bytes']
        for budget in (0,1,-256,2**30+256,2**64,1.5):
            rejects('invalid_budget_'+str(budget),lambda:Context(budget))
        context=Context(4096);contexts.append(context)
        s=context.stats();report['capabilities']=s
        check('preallocated_exact_budget',s['resident_bytes']==4096 and s['used_bytes']==0 and s['backing_buffer_allocations']==1)
        a=context.allocate(1028);b=context.allocate(1024);c=context.allocate(1792)
        check('alignment_charged_to_budget',context.stats()['used_bytes']==4096)
        rejects('exhaustion_rejected',lambda:context.allocate(1))
        check('failed_allocation_preserves_state',context.stats()['used_bytes']==4096 and context.stats()['active_allocations']==3)
        for handle,count,seed in ((a,257,3),(b,256,4),(c,448,5)):
            r=context.dispatch(handle,count,repeats=2,seed=seed)
            check('gpu_allocation_'+str(handle),r['status']=='PASS' and all(t is not None and t>=0 for t in r['gpu_command_ms']))
        check('neighbor_ranges_unchanged',context.verify(a,257,4)==0 and context.verify(b,256,5)==0)
        rejects('requested_size_boundary',lambda:context.dispatch(a,258))
        check('rejected_dispatch_keeps_neighbors',context.verify(b,256,5)==0)
        context.release(b)
        rejects('double_free_rejected',lambda:context.release(b))
        rejects('freed_dispatch_rejected',lambda:context.dispatch(b,1))
        d=context.allocate(1024)
        check('pooled_reuse_new_handle',d!=b and context.stats()['backing_buffer_allocations']==1)
        other=Context(1024);contexts.append(other);foreign=other.allocate(4)
        rejects('foreign_handle_rejected',lambda:context.release(foreign))
        for h in (a,c,d):context.release(h)
        check('coalesced_whole_arena',context.stats()['largest_free_bytes']==4096)
        whole=context.allocate(4096);check('whole_arena_reusable',context.dispatch(whole,1024)['status']=='PASS')
        context.close();context.close()
        check('close_invalidates_all_allocations',context.stats()['closed'] and context.stats()['resident_bytes']==0)
        rejects('closed_dispatch_rejected',lambda:context.dispatch(whole,1))
        rejects('closed_allocate_rejected',lambda:context.allocate(4))
        other.close()
        with Context(16*2**20) as pool:
            h=pool.allocate(4*2**20)
            for _ in range(8):report['timings'].append(pool.dispatch(h,1048576))
            pool.release(h)
            for _ in range(1000):
                h=pool.allocate(1028);pool.release(h)
            check('1000_pool_cycles_one_backing_buffer',pool.stats()['allocation_requests']==1001 and pool.stats()['backing_buffer_allocations']==1 and pool.stats()['used_bytes']==0)
        try:
            with Context(4096):raise RuntimeError('deliberate caller exception')
        except RuntimeError:pass
        check('exception_context_manager_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
        temporary=Context(8192);temporary.allocate(4);del temporary;gc.collect()
        check('capsule_destructor_cleanup',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
        for _ in range(32):
            with Context(4096) as transient:transient.dispatch(transient.allocate(1028),257)
        check('32_context_lifecycle_cycles',fluxfx_core.resource_status()['owned_buffer_bytes']==baseline)
        report['status']='PASS'
    except Exception:report['status']='FAIL';report['traceback']=traceback.format_exc()
    finally:
        for context in contexts:context.close()
    (ROOT/'test-results/resources-validation.json').write_text(json.dumps(report,indent=2))
    print('FLUXFX_RESOURCES',report['status'],report.get('traceback',''))
    return report
if __name__=='__main__':run()
