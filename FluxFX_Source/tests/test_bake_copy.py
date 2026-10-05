from array import array
from pathlib import Path
import tempfile
import unittest
from fluxfx.backend.device import BlenderGPUDevice
from fluxfx.physics.cache import CacheReader, CacheWriter, field_bytes, fingerprint, float32_view
from fluxfx.physics.config import GridSpec

try:
    import numpy as np
except ImportError:
    np = None


class ReadbackBuffer(array):
    """gpu.types.Buffer stand-in: buffer protocol, iteration and dimensions."""
    dimensions = None


class ListOnlyBuffer:
    """A Buffer from a Blender build without the buffer protocol."""
    def __init__(self, values):
        self.values = list(values)
        self.dimensions = None

    def __iter__(self):
        return iter(self.values)


class Texture:
    def __init__(self, buffer):
        self.buffer = buffer

    def read(self):
        return self.buffer


class Float32ViewTests(unittest.TestCase):
    def test_views_buffers_without_copying(self):
        data = array('f', [0.0, 1.5, -2.0, 3.25])
        view = float32_view(data, 4)
        self.assertEqual(view.tolist(), [0.0, 1.5, -2.0, 3.25])
        data[1] = 9.0
        self.assertEqual(view[1], 9.0)  # same memory, not a copy

    def test_flattens_multidimensional_contiguous_buffers(self):
        view = memoryview(array('f', range(24))).cast('B').cast('f', (4, 3, 2))
        self.assertEqual(float32_view(view, 24).tolist(), [float(i) for i in range(24)])

    def test_rejects_what_it_cannot_view(self):
        self.assertIsNone(float32_view([1.0, 2.0]))
        self.assertIsNone(float32_view(array('d', [1.0, 2.0])))
        with self.assertRaises(ValueError):
            float32_view(array('f', [1.0, 2.0]), 3)

    def test_field_bytes_converts_lists_and_checks_size(self):
        self.assertEqual(bytes(field_bytes([1.0, 2.0], 2)), array('f', [1.0, 2.0]).tobytes())
        with self.assertRaises(ValueError):
            field_bytes([1.0], 2)

    @unittest.skipIf(np is None, 'NumPy not installed')
    def test_numpy_arrays(self):
        values = np.arange(6, dtype=np.float32)
        self.assertEqual(float32_view(values, 6).tolist(), list(range(6)))
        self.assertIsNone(float32_view(np.arange(6, dtype=np.float64)))
        self.assertEqual(bytes(field_bytes(np.arange(6, dtype=np.float64), 6)), values.tobytes())
        strided = np.arange(12, dtype=np.float32)[::2]
        self.assertEqual(bytes(field_bytes(strided, 6)), np.ascontiguousarray(strided).tobytes())


class DeviceReadbackTests(unittest.TestCase):
    def test_read_array_is_flat_float32_x_fast(self):
        buffer = ReadbackBuffer('f', [float(i) for i in range(24)])
        result = BlenderGPUDevice.read_array(Texture(buffer), (4, 3, 2))
        self.assertEqual(len(result), 24)
        self.assertEqual([float(v) for v in result], [float(i) for i in range(24)])

    def test_read_keeps_list_contract(self):
        buffer = ReadbackBuffer('f', [0.5, 1.5, 2.5])
        result = BlenderGPUDevice.read(Texture(buffer), (3, 1, 1))
        self.assertIsInstance(result, list)
        self.assertEqual(result, [0.5, 1.5, 2.5])
        self.assertTrue(all(type(v) is float for v in result))

    def test_falls_back_without_buffer_protocol(self):
        buffer = ListOnlyBuffer([1.0, 2.0, 3.0, 4.0])
        result = BlenderGPUDevice.read_array(Texture(buffer), (2, 2, 1))
        self.assertEqual([float(v) for v in result], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(buffer.dimensions, (4,))

    def test_size_mismatch_is_an_error(self):
        with self.assertRaises(ValueError):
            BlenderGPUDevice.read_array(Texture(ReadbackBuffer('f', [1.0, 2.0])), (3, 1, 1))


class WriterInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.grid = GridSpec((2, 3, 4))
        self.count = 24
        self.density = [i / 7 for i in range(self.count)]
        self.temperature = [i - 12.5 for i in range(self.count)]

    def tearDown(self):
        self.temp.cleanup()

    def frame_bytes(self, convert, encoding='RAW'):
        writer = CacheWriter(self.temp.name, self.grid, ['DENSITY', 'TEMPERATURE'], 0, 0, 24,
                             fingerprint({'input': encoding}), encoding=encoding)
        writer.write(0, {'DENSITY': convert(self.density), 'TEMPERATURE': convert(self.temperature)})
        writer.finish()
        return writer.path, (writer.path / 'frame_0.fxc').read_bytes()

    def converters(self):
        found = {'list': list, 'array': lambda v: array('f', v),
                 'memoryview': lambda v: memoryview(array('f', v)),
                 'readback buffer': lambda v: ReadbackBuffer('f', v)}
        if np is not None:
            found['numpy'] = lambda v: np.asarray(v, dtype=np.float32)
        return found

    def test_raw_frames_are_byte_identical_for_every_input_type(self):
        _, reference = self.frame_bytes(list)
        for name, convert in self.converters().items():
            with self.subTest(input=name):
                self.assertEqual(self.frame_bytes(convert)[1], reference)

    def test_compressed_frames_round_trip_from_views(self):
        for name, convert in self.converters().items():
            with self.subTest(input=name):
                path, _ = self.frame_bytes(convert, 'AUTO_ZLIB')
                fields = CacheReader(path).read(0)
                self.assertEqual(list(fields['DENSITY']), list(array('f', self.density)))
                self.assertEqual(list(fields['TEMPERATURE']), list(array('f', self.temperature)))

    def test_invalid_view_values_are_rejected_and_leave_no_frame(self):
        writer = CacheWriter(self.temp.name, self.grid, ['DENSITY'], 0, 0, 24, fingerprint({'bad': 1}))
        bad = array('f', [0.0] * self.count); bad[5] = float('nan')
        with self.assertRaises(ValueError):
            writer.write(0, {'DENSITY': ReadbackBuffer('f', bad)})
        self.assertEqual(sorted(p.name for p in Path(writer.path).iterdir()), ['manifest.json'])


if __name__ == '__main__':
    unittest.main()
