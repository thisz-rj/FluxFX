"""Tiny synchronous dependency readback for completed-step playback budgets."""
from math import isfinite


class StepCompletion:
    def __init__(self, device):
        self.device = device
        self.names = ('densityField', 'temperatureField', 'velocityU', 'velocityV',
                      'velocityW', 'divergenceField', 'fuelField', 'flameField')
        self.kernel = device.kernel('benchmark_fence.glsl', samplers=self.names)
        self.pixel = device.texture((1, 1, 1))

    def wait(self, solver):
        fields = (solver.density, solver.temperature, *solver._velocity, solver.projector.after, solver.combustion.fuel if solver.combustion else solver.density, solver.combustion.flame if solver.combustion else solver.density)
        self.device.dispatch(self.kernel, self.pixel, (1, 1, 1), sources=dict(zip(self.names, fields)))
        if not isfinite(self.device.read(self.pixel, (1, 1, 1))[0]):
            raise RuntimeError('Nonfinite completion sample; reset simulation')

    def close(self):
        self.pixel = self.kernel = None
