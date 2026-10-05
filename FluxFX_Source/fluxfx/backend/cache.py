"""GPU readback for baking and a display-only cached field adapter."""
from .device import BlenderGPUDevice
from math import prod
import numpy as np


def capture(solver):
    channels = ['DENSITY', 'TEMPERATURE']
    if solver.combustion: channels += ['FUEL', 'FLAME']
    if solver.solids: channels += ['COLLISION']
    return {name: solver.device.read(solver.preview_field(name), solver.grid.shape) for name in channels}


class CachedFields:
    def __init__(self, grid):
        self.grid = grid
        self.device = BlenderGPUDevice()
        self.fields = {}
        self.texture = self.channel = None

    def upload(self, fields, channel='DENSITY'):
        # One CPU frame and one displayed GPU channel. Switching display channels
        # uploads from this CPU frame without rereading or rerunning the simulation.
        arrays = {}
        for name, values in fields.items():
            data = np.asarray(values, dtype=np.float32)
            if data.shape != (prod(self.grid.shape),) or not np.isfinite(data).all() or (name != 'TEMPERATURE' and (data < 0).any()):
                raise ValueError('Invalid cached texture data')
            arrays[name] = data
        self.fields = arrays
        self.texture = self.channel = None
        if channel in self.fields: self.preview_field(channel)

    def preview_field(self, channel):
        if channel != self.channel:
            data = self.fields[channel]
            buffer = self.device.gpu.types.Buffer('FLOAT', prod(self.grid.shape), data)
            texture = self.device.gpu.types.GPUTexture(self.grid.shape, format='R32F', data=buffer)
            texture.filter_mode(False)
            self.texture, self.channel = texture, channel
        return self.texture

    def close(self):
        self.fields.clear()
        self.texture = self.channel = None
