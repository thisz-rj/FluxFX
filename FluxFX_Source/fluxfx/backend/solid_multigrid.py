"""Topology-preserving aggregation V-cycles for static voxel obstacles."""
from math import prod
from .collision import SolidPressureProjector
from ..physics.solid_hierarchy import build_hierarchy, graph_inverse


class SolidMultigridProjector(SolidPressureProjector):
    def __init__(self,grid,settings=None,device=None):
        super().__init__(grid,settings,device)
        self.levels=[]
        mask=self.device.read(self.device.mask,grid.shape)
        hierarchy=build_hierarchy(grid.shape,grid.extent,mask)
        self.smooth_kernel=self.device.kernel('solid_mg_smooth.glsl',sample_input=True,
            samplers=('edgeField','divergenceField'),includes=('solid_mg_operator.glsl',))
        self.residual_kernel=self.device.kernel('solid_mg_residual.glsl',sample_input=True,
            samplers=('edgeField','divergenceField'),includes=('solid_mg_operator.glsl',))
        self.restrict_kernel=self.device.kernel('mg_restrict.glsl',sample_input=True)
        self.prolong_kernel=self.device.kernel('solid_mg_prolong.glsl',sample_input=True,
            samplers=('edgeField','coarseField'))
        for i,(shape,edges) in enumerate(hierarchy):
            self.levels.append(dict(shape=shape,edges=self.device.texture(shape,edges,channels=4),
                p=self.pressure if i==0 else self.device.texture(shape),
                q=self.spare if i==0 else self.device.texture(shape),
                rhs=self.before if i==0 else self.device.texture(shape),
                residual=self.device.texture(shape)))
        self.coarse_matrix=self.coarse_kernel=None
        shape,edges=hierarchy[-1]
        n=prod(shape)
        if n<=256 and self.settings.coarse_solver=='DIRECT' and len(hierarchy)>1:
            self.coarse_matrix=self.device.texture((n,n,1),graph_inverse(shape,edges),nonnegative=False)
            self.coarse_kernel=self.device.kernel('solid_mg_direct.glsl',sample_input=True,samplers=('inverseField',))
        self.last_cycles=0

    @property
    def allocated_bytes(self):
        return super().allocated_bytes+4*sum(prod(v['shape'])*(5 if i==0 else 8)
                                               for i,v in enumerate(self.levels))+(4*prod(self.levels[-1]['shape'])**2 if self.coarse_matrix is not None else 0)

    def smooth(self,level,count):
        for _ in range(count):
            self.device.dispatch(self.smooth_kernel,level['q'],level['shape'],input_field=level['p'],
                sources={'edgeField':level['edges'],'divergenceField':level['rhs']})
            level['p'],level['q']=level['q'],level['p']
            self.last_iterations+=1

    def cycle(self,index):
        level=self.levels[index]
        if index==len(self.levels)-1:
            if self.coarse_kernel is not None:
                self.device.dispatch(self.coarse_kernel,level['q'],level['shape'],input_field=level['rhs'],
                    sources={'inverseField':self.coarse_matrix})
                level['p'],level['q']=level['q'],level['p']
            else:self.smooth(level,80)
            return
        self.smooth(level,4)
        self.device.dispatch(self.residual_kernel,level['residual'],level['shape'],input_field=level['p'],
            sources={'edgeField':level['edges'],'divergenceField':level['rhs']})
        coarse=self.levels[index+1]
        self.device.dispatch(self.restrict_kernel,coarse['rhs'],coarse['shape'],input_field=level['residual'])
        coarse['p'].clear(format='FLOAT',value=(0.0,))
        self.cycle(index+1)
        self.device.dispatch(self.prolong_kernel,level['q'],level['shape'],input_field=level['p'],
            sources={'edgeField':level['edges'],'coarseField':coarse['p']})
        level['p'],level['q']=level['q'],level['p']
        self.smooth(level,4)

    def solve_pressure(self,dt,previous_dt):
        self.last_cycles=0
        if len(self.levels)==1:
            return super().solve_pressure(dt,previous_dt)
        self.pressure.clear(format='FLOAT',value=(0.0,))
        self.levels[0]['p'],self.levels[0]['q']=self.pressure,self.spare
        self.last_iterations=0
        self.last_cycles=self.settings.pressure_cycles*(self.settings.pressure_cold_multiplier if previous_dt is None else 1)
        for _ in range(self.last_cycles):self.cycle(0)
        self.pressure,self.spare=self.levels[0]['p'],self.levels[0]['q']

    def reset(self):
        super().reset()
        self.last_cycles=0
        for level in self.levels[1:]:
            for name in ('p','q','rhs','residual'):level[name].clear(format='FLOAT',value=(0.0,))

    def metrics(self):
        return super().metrics() | {'solver':'SOLID_MULTIGRID' if self.last_cycles else 'SOLID_JACOBI',
            'v_cycles':self.last_cycles,'levels':[v['shape'] for v in self.levels],
            'coarse_solver':'graph_pseudoinverse' if self.coarse_matrix is not None else 'masked_smoothing','aggregation':'connected_children_only'}

    def close(self):
        self.levels=[]
        self.coarse_matrix=self.coarse_kernel=None
        self.smooth_kernel=self.residual_kernel=self.restrict_kernel=self.prolong_kernel=None
        super().close()
