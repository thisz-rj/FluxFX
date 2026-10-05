import unittest
from types import SimpleNamespace
from fluxfx.backend.completion import (SLOTS, SimulationFault, StepCompletion, classify,
                                       guarded_fields, reduction_shapes)
from fluxfx.physics.config import GridSpec


class FakeTexture:
    def __init__(self, shape):
        self.shape = shape


class FakeDevice:
    """Records dispatches; read() returns the maxima a test wants the GPU to report."""
    def __init__(self, maxima):
        self.maxima, self.dispatches = maxima, []

    def kernel(self, filename, constants=(), sample_input=False, samplers=(), **_):
        return SimpleNamespace(filename=filename, samplers=samplers)

    def texture(self, shape):
        return FakeTexture(shape)

    def dispatch(self, shader, output, shape, uniforms=None, input_field=None, sources=None):
        self.dispatches.append((shader.filename, shape, input_field, dict(sources or {})))

    def read(self, texture, shape):
        return list(self.maxima) + [0.0] * (SLOTS - len(self.maxima))


def solver(n=128, combustion=False):
    grid = GridSpec((n, n, n))
    return SimpleNamespace(
        grid=grid, density=FakeTexture(grid.shape), temperature=FakeTexture(grid.shape),
        _velocity=[FakeTexture(s) for s in grid.face_shapes],
        combustion=SimpleNamespace(fuel=FakeTexture(grid.shape), flame=FakeTexture(grid.shape)) if combustion else None,
        steps=37, time=1.2345, faulted=False, projector=SimpleNamespace(ready=True))


class GuardTests(unittest.TestCase):
    def test_reduction_levels_fit_the_combine_scan(self):
        self.assertEqual(reduction_shapes((128, 128, 128)), [(32, 32, 32), (8, 8, 8)])
        self.assertEqual(reduction_shapes((129, 128, 128)), [(33, 32, 32), (9, 8, 8)])
        self.assertEqual(reduction_shapes((16, 16, 16)), [(4, 4, 4)])
        self.assertEqual(reduction_shapes((2, 2, 2)), [(1, 1, 1)])

    def test_guards_every_field_including_combustion(self):
        self.assertEqual([name for name, _, _ in guarded_fields(solver())],
                         ['density', 'temperature', 'velocity U', 'velocity V', 'velocity W'])
        self.assertEqual([name for name, _, _ in guarded_fields(solver(combustion=True))][-2:], ['fuel', 'flame'])

    def test_one_combine_and_one_small_readback_per_step(self):
        device = FakeDevice([1.0] * 7)
        state = solver(combustion=True)
        StepCompletion(device).wait(state)
        reduces = [d for d in device.dispatches if d[0] == 'max_reduce.glsl']
        combines = [d for d in device.dispatches if d[0] == 'guard_combine.glsl']
        self.assertEqual(len(reduces), 14)  # 7 fields x 2 levels at 128^3
        self.assertEqual(len(combines), 1)
        sources = combines[0][3]
        self.assertEqual(sorted(sources), [f'field{i}' for i in range(SLOTS)])
        self.assertEqual(sources['field0'].shape, (8, 8, 8))
        self.assertIs(sources['field7'], sources['field7'])  # unused slot bound to the empty texture
        self.assertEqual(sources['field7'].shape, (1, 1, 1))
        self.assertFalse(state.faulted)
        # Each chain reads the field itself first, then its own previous level.
        first = reduces[0]
        self.assertIs(first[2], state.density)

    def test_invalid_value_anywhere_faults_with_a_useful_message(self):
        state = solver()
        guard = StepCompletion(FakeDevice([0.5, 120.0, 3.4e38, 1.0, float('nan')]))
        with self.assertRaises(SimulationFault) as caught:
            guard.wait(state)
        message = str(caught.exception)
        self.assertIn('velocity U (NaN/Inf)', message)
        self.assertIn('velocity W (NaN/Inf)', message)
        self.assertNotIn('density', message)
        self.assertIn('step 37', message)
        self.assertIn('press Reset', message)
        self.assertTrue(state.faulted)
        self.assertFalse(state.projector.ready)
        self.assertEqual(guard.maxima['temperature'], 120.0)

    def test_classification(self):
        self.assertEqual(classify([0.0, 1e29], ['a', 'b']), [])
        self.assertEqual(classify([2e30], ['a']), ['a (|value| 2e+30)'])
        self.assertEqual(classify([float('inf'), 3.4e38], ['a', 'b']), ['a (NaN/Inf)', 'b (NaN/Inf)'])

    def test_simulation_fault_is_a_runtime_error(self):
        self.assertTrue(issubclass(SimulationFault, RuntimeError))


if __name__ == '__main__':
    unittest.main()
