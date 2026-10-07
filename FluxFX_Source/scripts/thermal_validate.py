"""P0.4 GPU suite; call run_suite() in a graphical Blender context."""
from dataclasses import replace
from pathlib import Path
import math
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_suite():
    from fluxfx.backend.thermal import DenseThermalAdvection
    from fluxfx.backend.mac import DenseMACAdvection
    from fluxfx.backend.diagnostics import collect
    from fluxfx.physics.config import GridSpec
    from fluxfx.physics.thermal import ThermalSettings
    from fluxfx.physics.mac_reference import seed_velocity
    from fluxfx.physics.thermal_reference import step
    report={'diagnostics':collect(True), 'tests':[]}
    assert report['diagnostics']['status']=='READY'
    grid=GridSpec((7,5,3), (1.3,1.1,.9))
    settings=ThermalSettings(source_radius=.3)
    density=[((i*7)%13)/13 for i in range(math.prod(grid.shape))]
    temp=[((i*11)%19-5)*3. for i in range(math.prod(grid.shape))]
    for name, params in (
        ('coupled_signed_temperature',settings),
        ('cooling_only',replace(settings,thermal_lift=0,density_weight=0,source_rate=0,heat_source_rate=0)),
        ('negative_heat_source',replace(settings,heat_source_rate=-50))):
        solver=DenseThermalAdvection(grid,params)
        try:
            original_temperature=solver.read_temperature()
            solver.upload(density)
            solver.upload_temperature(temp)
            velocity=seed_velocity(grid,params)
            d,t=density,temp
            for _ in range(4):
                d,t,velocity=step(d,t,velocity,grid,params,.04)
                solver.step(.04)
            error_d=max(abs(a-b) for a,b in zip(d,solver.read_density()))
            error_t=max(abs(a-b) for a,b in zip(t,solver.read_temperature()))
            error_v=max(abs(a-b) for aa,bb in zip(velocity,solver.read_velocity()) for a,b in zip(aa,bb))
            assert error_d<2e-5 and error_t<5e-4 and error_v<2e-5,(name,error_d,error_t,error_v)
            solver.reset()
            assert solver.read_temperature()==original_temperature
            solver.reset(seed=False)
            assert not any(solver.read_temperature()) and not any(solver.read_density())
            report['tests'].append({'name':name,'status':'PASS','steps':4,
                'density_error':error_d,'temperature_error':error_t,'velocity_error':error_v})
        finally:
            solver.close()
    # Exact uniform force, including both domain boundary faces.
    for name, theta, rho in (('hot_rises',100.,0.),('cold_sinks',-100.,0.),('density_sinks',0.,1.),('equilibrium',10.,1.)):
        params=replace(settings,source_rate=0,heat_source_rate=0)
        solver=DenseThermalAdvection(grid,params)
        try:
            solver.upload([rho]*math.prod(grid.shape))
            solver.upload_temperature([theta]*math.prod(grid.shape))
            solver.step(.1)
            velocity=solver.read_velocity()
            expected=.1*(params.thermal_lift*theta-params.density_weight*rho)
            assert max(abs(v-expected) for v in velocity[2])<2e-7
            assert not any(velocity[0]) and not any(velocity[1])
            report['tests'].append({'name':name,'status':'PASS','expected_w':expected})
        finally:
            solver.close()
    params=replace(settings,thermal_lift=0,density_weight=0,velocity=(.1,-.2,.3),angular_speed=.7)
    mac=DenseMACAdvection(grid,params)
    thermal=DenseThermalAdvection(grid,params)
    try:
        for _ in range(4):
            mac.step(.04); thermal.step(.04)
        assert mac.read_density()==thermal.read_density()
        assert mac.read_velocity()==thermal.read_velocity()
        report['tests'].append({'name':'zero_force_matches_mac_exactly','status':'PASS'})
    finally:
        mac.close(); thermal.close()
    for n in (64,128):
        solver=DenseThermalAdvection(GridSpec((n,)*3))
        try:
            for _ in range(30):
                solver.step()
            d=solver.read_density(); t=solver.read_temperature(); v=solver.read_velocity()
            assert all(math.isfinite(x) and x>=0 for x in d)
            assert all(math.isfinite(x) for x in t)
            assert all(math.isfinite(x) for f in v for x in f)
            assert max(t)>0 and max(v[2])>0
            report['tests'].append({'name':f'thermal_{n}_30_steps','status':'PASS',
                'field_bytes':solver.allocated_bytes,'max_temperature':max(t),'max_vertical_speed':max(v[2])})
            del d,t,v
        finally:
            solver.close()
    report['status']='PASS'
    return report
