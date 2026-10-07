"""GPU maxima reductions; read only five scalar bounds, never complete fields."""
from math import prod, isfinite
from ..physics.timestep import choose_timestep


class AdaptiveTimestep:
    def __init__(self, grid, device):
        self.device=device
        self.grid=grid
        self.kernel=device.kernel('max_reduce.glsl',sample_input=True)
        self.chains=[]
        for shape in (*grid.face_shapes,grid.shape,grid.shape):
            chain=[]
            while True:
                shape=tuple((n+3)//4 for n in shape)
                chain.append((shape,device.texture(shape)))
                if shape==(1,1,1): break
            self.chains.append(chain)

    @property
    def allocated_bytes(self):
        return 4*sum(prod(s) for chain in self.chains for s,t in chain)

    def bounds(self, solver):
        fields=(*solver._velocity,solver.density,solver.temperature)
        for source,chain in zip(fields,self.chains):
            for shape,target in chain:
                self.device.dispatch(self.kernel,target,shape,input_field=source)
                source=target
        maxima=[self.device.read(chain[-1][1],(1,1,1))[0] for chain in self.chains]
        if any(not isfinite(v) or v>=1e30 for v in maxima):
            raise RuntimeError('Nonfinite or excessive field values; reset simulation')
        return maxima

    def select(self,solver,max_dt,cfl,emission=None,sources=None):
        u,v,w,density,temperature=self.bounds(solver)
        motions=[s.motion for s in sources] if sources is not None else ([emission] if emission is not None else [])
        for motion in motions:
            if motion.coupling > 0:
                u,v,w=(max(current,abs(target)) for current,target in zip((u,v,w),motion.velocity))
        h=self.grid.cell_size
        rate=sum(speed/spacing for speed,spacing in zip((u,v,w),h))
        acceleration=(solver.settings.thermal_lift*temperature+solver.settings.density_weight*density)/h[2]
        if solver.settings.vorticity_strength>0:
            acceleration+=solver.settings.vorticity_limit*sum(1/spacing for spacing in h)
        if solver.settings.turbulence_strength>0:
            acceleration+=min(solver.settings.turbulence_strength,solver.settings.turbulence_limit)*sum(1/spacing for spacing in h)
        quantized=(solver.settings.timestep_policy=="QUANTIZED" or (solver.settings.timestep_policy=="AUTO" and not solver.projector.uses_impulse))
        dt=choose_timestep(max_dt,cfl,rate,acceleration,quantized=quantized)
        return {'dt':dt,'max_dt':max_dt,'target':cfl,'rate_bound':rate,
                'acceleration_rate_bound':acceleration,
                'estimated_courant':rate*dt+acceleration*dt*dt,
                'policy':'QUANTIZED' if quantized else 'CONTINUOUS', 'max_abs_velocity':[u,v,w], 'mode':'ADAPTIVE'}

    def close(self):
        self.chains=[]
        self.kernel=None
