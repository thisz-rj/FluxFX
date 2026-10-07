"""Independent CPU checks for MG transfer/residual kernels and lifecycle."""
from pathlib import Path
from math import prod,sin
from dataclasses import replace
import json
ROOT=Path(__file__).resolve().parents[1]


def run_suite():
    from fluxfx.backend.multigrid import MultigridPressureProjector
    from fluxfx.backend.device import BlenderGPUDevice
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.pressure import PressureSettings
    from fluxfx.physics.pressure_reference import cells,index,laplacian,walls,divergence
    device=BlenderGPUDevice();grid=GridSpec((8,8,8),(1.3,.8,1.7))
    mg=MultigridPressureProjector(grid,PressureSettings(pressure_warm_start="LEGACY",pressure_cycles=4),device=device)
    report={'status':'RUNNING','tests':[]}
    def record(name):report['tests'].append({'name':name,'status':'PASS'})
    try:
        pressure=[sin(i*.21) for i in range(512)];rhs=[sin(i*.13) for i in range(512)]
        p=device.texture(grid.shape,pressure,nonnegative=False)
        b=device.texture(grid.shape,rhs,nonnegative=False)
        out=device.texture(grid.shape)
        device.dispatch(mg.residual_kernel,out,grid.shape,{'invCell':mg.inv_cell,'dt':.04},p,sources={'divergenceField':b})
        actual=device.read(out,grid.shape)
        expected=[r/.04-l for r,l in zip(rhs,laplacian(pressure,grid))]
        assert max(abs(a-b) for a,b in zip(actual,expected))<1e-4
        record('residual_matches_cpu_neumann_laplacian')
        coarse=device.texture((4,4,4))
        device.dispatch(mg.restrict_kernel,coarse,(4,4,4),input_field=p)
        expected=[sum(pressure[index((2*x+i,2*y+j,2*z+k),grid.shape)] for k in range(2) for j in range(2) for i in range(2))/8 for x,y,z in cells((4,4,4))]
        assert max(abs(a-b) for a,b in zip(device.read(coarse,(4,4,4)),expected))<1e-6
        record('restriction_matches_eight_cell_average')
        # A constant correction must be preserved, including boundary corners.
        coarse.clear(format='FLOAT',value=(2.,))
        device.dispatch(mg.prolong_kernel,out,grid.shape,input_field=p,sources={'coarseField':coarse})
        assert max(abs(a-b-2) for a,b in zip(device.read(out,grid.shape),pressure))<1e-6
        # Linear x on coarse centres should interpolate exactly away from clamped edge.
        coarse=device.texture((4,4,4),[(x+.5)/4 for x,y,z in cells((4,4,4))])
        device.dispatch(mg.prolong_kernel,out,grid.shape,input_field=p,sources={'coarseField':coarse})
        expected=[min(.875,max(.125,(x+.5)/8)) for x,y,z in cells(grid.shape)]
        assert max(abs(a-b-c) for a,b,c in zip(device.read(out,grid.shape),pressure,expected))<1e-6
        record('prolongation_constant_linear_and_boundary_extension')
        # Independent GPU verification of the direct 4³ Neumann solve.
        level=mg.levels[-1]
        rhs=[sin(i*.73) for i in range(64)];mean=sum(rhs)/64
        rhs=[v-mean for v in rhs]
        level['rhs']=device.texture((4,4,4),rhs,nonnegative=False)
        mg.cycle(len(mg.levels)-1,1.)
        p4=device.read(level['p'],(4,4,4))
        equation=laplacian(p4,GridSpec((4,4,4),grid.extent))
        assert max(abs(a-b) for a,b in zip(equation,rhs))<2e-6
        record('direct_coarse_solve_matches_neumann_equation')
        fields=[device.texture(s) for s in grid.face_shapes];outputs=[device.texture(s) for s in grid.face_shapes]
        mg.project(fields,outputs,.04)
        assert mg.metrics()['ratio']==0
        record('zero_velocity_stays_zero')
        velocity=[[sin(i*.63)*.5 for i in range(prod(s))] for s in grid.face_shapes]
        fields=[device.texture(s,v,nonnegative=False) for s,v in zip(grid.face_shapes,velocity)]
        mg.project(fields,outputs,.04)
        result=[device.read(f,s) for f,s in zip(outputs,grid.face_shapes)]
        assert tuple(result)==walls(result,grid)
        gpu_div=device.read(mg.after,grid.shape)
        assert max(abs(a-b) for a,b in zip(gpu_div,divergence(result,grid)))<1e-5
        assert mg.metrics()['ratio']<.01
        record('random_signed_flow_and_wall_divergence')
        mg.project(fields,outputs,.02)
        dt_changed=[device.read(f,s) for f,s in zip(outputs,grid.face_shapes)]
        mg.reset()
        assert not mg.ready and mg.last_dt is None
        mg.project(fields,outputs,.02)
        reset_result=[device.read(f,s) for f,s in zip(outputs,grid.face_shapes)]
        assert max(abs(a-b) for aa,bb in zip(dt_changed,reset_result) for a,b in zip(aa,bb))<1e-6
        record('dt_change_and_reset_clear_all_corrections')
        mg.settings=replace(mg.settings,pressure_cycles=2)
        mg.project(fields,outputs,.02)
        assert mg.last_cycles==2
        record('live_cycle_budget')
        report['status']='PASS'
    finally:mg.close()
    (ROOT/'test-results/multigrid-operators.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FLUXFX_MG_OPERATORS',report)
    return report

if __name__=='__main__':run_suite()
