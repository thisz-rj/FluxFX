"""Fuel storage and split GPU reaction; no Blender UI dependencies."""
from math import prod

class CombustionPasses:
    def __init__(self, grid, device):
        self.grid,self.device=grid,device
        self.fuel=device.texture(grid.shape)
        self.spare=device.texture(grid.shape)
        self.flame=device.texture(grid.shape) # consumed fuel per second in last step
        self.burn=device.kernel('combustion_burn.glsl',(('FLOAT','dt'),('FLOAT','ignitionTemperature'),('FLOAT','burnRate')),
            sample_input=True,samplers=('temperatureField',))
        self.apply=device.kernel('combustion_apply.glsl',(('FLOAT','dt'),('FLOAT','yieldValue')),
            sample_input=True,samplers=('burnField',))

    @property
    def allocated_bytes(self):return 12*prod(self.grid.shape)

    def reset(self):
        for field in (self.fuel,self.spare,self.flame):field.clear(format='FLOAT',value=(0.,))

    def react(self, solver, dt):
        s=solver.settings
        self.device.dispatch(self.burn,self.flame,self.grid.shape,
            {'dt':dt,'ignitionTemperature':s.ignition_temperature,'burnRate':s.burn_rate},self.fuel,
            sources={'temperatureField':solver.temperature})
        for front,back,value in ((self.fuel,self.spare,-1.),(solver._front,solver._back,s.smoke_yield),
                                  (solver._temperature,solver._temperature_back,s.heat_yield)):
            self.device.dispatch(self.apply,back,self.grid.shape,{'dt':dt,'yieldValue':value},front,sources={'burnField':self.flame})
        self.fuel,self.spare=self.spare,self.fuel
        solver._front,solver._back=solver._back,solver._front
        solver._temperature,solver._temperature_back=solver._temperature_back,solver._temperature

    def close(self):self.fuel=self.spare=self.flame=self.burn=self.apply=None
