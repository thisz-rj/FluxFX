"""Completed-step fence that also guards every field against NaN/Inf.

Each wait reduces density, temperature, the three face velocities and, with
combustion, fuel and flame to their maximum magnitude on the GPU (the existing
max_reduce kernel, which maps NaN/Inf to a 3.4e38 sentinel), combines those
maxima into one 8-texel texture and reads only those 8 floats back. An invalid
value anywhere in any guarded field is therefore caught after every step, in
fixed and adaptive timestep modes alike. The readback still waits for the
completed step, which playback budgets and benchmarks rely on.
"""
from math import isfinite, prod

SLOTS = 8               # guard_combine.glsl field slots
COMBINE_LIMIT = 1024    # texels each combine invocation scans serially
EXCESSIVE = 1e30        # same bound as the adaptive timestep's reductions
NONFINITE = 3e38        # max_reduce/guard_combine NaN/Inf sentinel is 3.4e38


class SimulationFault(RuntimeError):
    """Invalid field values; the solver stays faulted until Reset."""


def reduction_shapes(shape):
    """max_reduce levels (4^3 per texel) until a level fits COMBINE_LIMIT."""
    levels = []
    while not levels or prod(levels[-1]) > COMBINE_LIMIT:
        shape = tuple((n + 3) // 4 for n in shape)
        levels.append(shape)
    return levels


def guarded_fields(solver):
    """(name, texture, shape) for every field the guard checks."""
    grid = solver.grid
    fields = [('density', solver.density, grid.shape), ('temperature', solver.temperature, grid.shape),
              *((f'velocity {axis}', texture, shape)
                for axis, texture, shape in zip('UVW', solver._velocity, grid.face_shapes))]
    if solver.combustion:
        fields += [('fuel', solver.combustion.fuel, grid.shape), ('flame', solver.combustion.flame, grid.shape)]
    return fields


def classify(maxima, names):
    """Human-readable problems for maxima read back from the guard."""
    problems = []
    for name, value in zip(names, maxima):
        if not isfinite(value) or value >= NONFINITE:
            problems.append(f'{name} (NaN/Inf)')
        elif value >= EXCESSIVE:
            problems.append(f'{name} (|value| {value:.3g})')
    return problems


class StepCompletion:
    def __init__(self, device):
        self.device = device
        self.names = tuple(f'field{i}' for i in range(SLOTS))
        self.reduce = device.kernel('max_reduce.glsl', sample_input=True)
        self.combine = device.kernel('guard_combine.glsl', samplers=self.names)
        self.result = device.texture((SLOTS, 1, 1))
        self.empty = device.texture((1, 1, 1))
        self.chains = {}
        self.maxima = {}

    def chain(self, slot, shape):
        key = (slot, shape)
        if key not in self.chains:
            self.chains[key] = [(level, self.device.texture(level)) for level in reduction_shapes(shape)]
        return self.chains[key]

    def wait(self, solver):
        fields = guarded_fields(solver)
        finals = {}
        for slot, (_, texture, shape) in enumerate(fields):
            source = texture
            for level, target in self.chain(slot, shape):
                self.device.dispatch(self.reduce, target, level, input_field=source)
                source = target
            finals[self.names[slot]] = source
        for slot in range(len(fields), SLOTS):
            finals[self.names[slot]] = self.empty
        self.device.dispatch(self.combine, self.result, (SLOTS, 1, 1), sources=finals)
        values = self.device.read(self.result, (SLOTS, 1, 1))[:len(fields)]
        self.maxima = {name: value for (name, _, _), value in zip(fields, values)}
        problems = classify(values, [name for name, _, _ in fields])
        if problems:
            solver.faulted = True
            if getattr(solver, 'projector', None) is not None:
                solver.projector.ready = False
            raise SimulationFault(
                f"Invalid simulation values after step {solver.steps} (t = {solver.time:.3f} s) in "
                f"{', '.join(problems)}. The simulation was stopped; press Reset. "
                "Try a smaller max step or CFL target, or weaker forces.")

    def close(self):
        self.chains = {}
        self.result = self.empty = self.reduce = self.combine = None
