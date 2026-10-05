"""Actual GPU max reduction and adaptive stepping validation."""
from pathlib import Path
from math import prod
import json
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    from fluxfx.backend.projected import DenseProjectedSmoke
    from fluxfx.backend.timestep import AdaptiveTimestep
    from fluxfx.backend.diagnostics import collect
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    report={'diagnostics':collect(True),'tests':[]}
    grid=GridSpec((9,7,5),(1.3,.8,1.7))
    solver=DenseProjectedSmoke(grid)
    controller=AdaptiveTimestep(grid,solver.device)
    try:
        arrays=[[((i*13)%31-15)*.13 for i in range(prod(s))] for s in grid.face_shapes]
        solver.upload_velocity(arrays)
        density=[i*.002 for i in range(prod(grid.shape))]
        temperature=[-i*.5 for i in range(prod(grid.shape))]
        solver.upload(density);solver.upload_temperature(temperature)
        actual=controller.bounds(solver)
        expected=[max(map(abs,a)) for a in (*arrays,density,temperature)]
        assert max(abs(a-b) for a,b in zip(actual,expected))<2e-6
        result=controller.select(solver,.033333333,.75)
        assert result['estimated_courant']<=.75 and result['dt']<result['max_dt']
        report['tests'].append({'name':'noncubic_signed_reduction','status':'PASS','bounds':actual,**result})
        solver.density.clear(format='FLOAT',value=(float('nan'),))
        try:
            controller.bounds(solver)
            raise AssertionError('NaN not detected')
        except RuntimeError: pass
        report['tests'].append({'name':'nan_rejection','status':'PASS'})
    finally:
        controller.close();solver.close()
    for n,steps in ((64,90),(128,20)):
        solver=DenseProjectedSmoke(GridSpec((n,n,n)))
        controller=AdaptiveTimestep(solver.grid,solver.device)
        dts=[]
        try:
            for i in range(steps):
                result=controller.select(solver,1/30,.75)
                assert result['estimated_courant']<=.750001
                solver.step(result['dt']);dts.append(result['dt'])
            assert abs(solver.time-sum(dts))<1e-10
            if n==64: assert min(dts)<max(dts), dts
            report['tests'].append({'name':f'adaptive_{n}_{steps}_steps','status':'PASS',
                'min_dt':min(dts),'max_dt':max(dts),'simulation_time':solver.time,
                'reduction_bytes':controller.allocated_bytes,'last_selection':result,
                'projection':solver.measure_projection()})
        finally:
            controller.close();solver.close()
    report['status']='PASS'
    (ROOT/'test-results/timestep-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_TIMESTEP',report)
    return report

if __name__=='__main__': run_suite()
