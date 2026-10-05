"""Geometric V-cycle pressure solver for evenly coarsenable cell grids."""
from math import prod
from .pressure import PressureProjector


def hierarchy_shapes(shape):
    result=[shape]
    while min(shape)>=8 and all(n%2==0 for n in shape):
        shape=tuple(n//2 for n in shape)
        result.append(shape)
    return result


def use_multigrid(grid, settings):
    return (len(hierarchy_shapes(grid.shape)) > 1 and
            (settings.pressure_solver == "MULTIGRID" or
             (settings.pressure_solver == "AUTO" and min(grid.shape) >= 16)))


class MultigridPressureProjector(PressureProjector):
    def __init__(self,grid,settings=None,device=None):
        super().__init__(grid,settings,device)
        self.levels=[]
        self.coarse_kernel=self.coarse_matrix=None
        shapes=hierarchy_shapes(grid.shape)
        self.residual_kernel=self.device.kernel('mg_residual.glsl',(('VEC3','invCell'),('FLOAT','dt')),
                                                sample_input=True,samplers=('divergenceField',))
        self.restrict_kernel=self.device.kernel('mg_restrict.glsl',sample_input=True)
        self.prolong_kernel=self.device.kernel('mg_prolong.glsl',sample_input=True,samplers=('coarseField',))
        for i,shape in enumerate(shapes):
            self.levels.append({'shape':shape,'inv':tuple(n/e for n,e in zip(shape,grid.extent)),
                'p':self.pressure if i==0 else self.device.texture(shape),
                'q':self.spare if i==0 else self.device.texture(shape),
                'rhs':self.before if i==0 else self.device.texture(shape),
                'residual':self.device.texture(shape)})
        self.last_cycles=0
        self.last_coarse_solves=0

    @property
    def allocated_bytes(self):
        return super().allocated_bytes+4*sum(prod(v['shape'])*(1 if i==0 else 4) for i,v in enumerate(self.levels))+(16384 if self.coarse_matrix is not None else 0)

    def reset(self):
        super().reset()
        self.last_cycles=0
        for i,level in enumerate(self.levels):
            for name in (('residual',) if i==0 else ('p','q','rhs','residual')):
                level[name].clear(format='FLOAT',value=(0.0,))

    def smooth(self,level,dt,count):
        for _ in range(count):
            self.device.dispatch(self.jacobi,level['q'],level['shape'],
                {'invCell':level['inv'],'dt':dt,'relaxation':2/3},level['p'],sources={'divergenceField':level['rhs']})
            level['p'],level['q']=level['q'],level['p']
            self.last_iterations+=1

    def cycle(self,index,dt):
        level=self.levels[index]
        if index==len(self.levels)-1:
            if level['shape']==(4,4,4) and self.settings.coarse_solver=='DIRECT':
                if self.coarse_kernel is None:
                    from ..physics.coarse_pressure import coarse_inverse
                    self.coarse_matrix=self.device.texture((64,64,1),coarse_inverse(tuple(self.grid.extent)),nonnegative=False)
                    self.coarse_kernel=self.device.kernel('coarse_pressure.glsl',(('FLOAT','dt'),),sample_input=True,samplers=('inverseField',))
                self.device.dispatch(self.coarse_kernel,level['q'],level['shape'],{'dt':dt},
                    level['rhs'],sources={'inverseField':self.coarse_matrix})
                level['p'],level['q']=level['q'],level['p']
                self.last_coarse_solves+=1
            else:
                self.smooth(level,dt,80)
            return
        self.smooth(level,dt,3)
        self.device.dispatch(self.residual_kernel,level['residual'],level['shape'],
            {'invCell':level['inv'],'dt':dt},level['p'],sources={'divergenceField':level['rhs']})
        coarse=self.levels[index+1]
        self.device.dispatch(self.restrict_kernel,coarse['rhs'],coarse['shape'],input_field=level['residual'])
        coarse['p'].clear(format='FLOAT',value=(0.0,))
        self.cycle(index+1,1.0)
        self.device.dispatch(self.prolong_kernel,level['q'],level['shape'],input_field=level['p'],sources={'coarseField':coarse['p']})
        level['p'],level['q']=level['q'],level['p']
        self.smooth(level,dt,3)

    def solve_pressure(self,dt,previous_dt):
        self.last_coarse_solves=0
        if len(self.levels)==1:
            self.last_cycles=0
            super().solve_pressure(dt,previous_dt)
            return
        if previous_dt!=dt:
            self.pressure.clear(format='FLOAT',value=(0.0,))
        self.levels[0]['p'],self.levels[0]['q']=self.pressure,self.spare
        self.last_iterations=0
        self.last_cycles=self.settings.pressure_cycles
        for _ in range(self.last_cycles): self.cycle(0,dt)
        self.pressure,self.spare=self.levels[0]['p'],self.levels[0]['q']

    def metrics(self):
        return super().metrics()|{'solver':'MULTIGRID' if self.last_cycles else 'JACOBI_FALLBACK',
            'v_cycles':self.last_cycles,'direct_coarse_solves':self.last_coarse_solves,'levels':[v['shape'] for v in self.levels],
            'iteration_meaning':'Jacobi smoothing passes summed across all levels'}

    def close(self):
        self.levels=[]
        self.coarse_kernel=self.coarse_matrix=None
        self.residual_kernel=self.restrict_kernel=self.prolong_kernel=None
        super().close()
