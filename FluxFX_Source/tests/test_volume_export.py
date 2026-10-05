import json
from pathlib import Path
import tempfile
import unittest
from fluxfx.physics import volume_export as ve

try:
    import numpy as np
except ImportError:
    np = None


class FakeGrid:
    def __init__(self, background=0.0):
        self.background, self.array, self.name, self.gridClass, self.transform = background, None, '', None, None
        self.tolerance = None

    def copyFromArray(self, array, tolerance=0.0):
        self.array, self.tolerance = array.copy(), tolerance

    def activeVoxelCount(self):
        return int((self.array != self.background).sum())


class FakeVDB:
    """Records grids; writes a small JSON stand-in so files exist on disk."""
    GridClass = type('GridClass', (), {'FOG_VOLUME': 'FOG_VOLUME'})

    def __init__(self, fail_on=None):
        self.written, self.fail_on = [], fail_on

    def FloatGrid(self, background=0.0):
        return FakeGrid(background)

    def createLinearTransform(self, matrix):
        return ('linear', tuple(tuple(row) for row in matrix))

    def write(self, path, grids, metadata):
        if self.fail_on is not None and len(self.written) == self.fail_on:
            Path(path).write_text('partial')
            raise RuntimeError('disk full')
        self.written.append((path, grids, metadata))
        Path(path).write_text(json.dumps([g.name for g in grids]))


class PlanTests(unittest.TestCase):
    def test_grids_follow_available_channels(self):
        names = [g.name for g in ve.plan_grids(('DENSITY', 'TEMPERATURE', 'FUEL', 'FLAME', 'COLLISION'))]
        self.assertEqual(names, ['density', 'heat', 'temperature', 'flame', 'fuel'])
        self.assertEqual([g.name for g in ve.plan_grids(('DENSITY',))], ['density'])

    def test_temperature_is_absolute_kelvin_with_ambient_background(self):
        temperature = next(g for g in ve.plan_grids(('TEMPERATURE',), ambient=300.0) if g.name == 'temperature')
        self.assertEqual((temperature.offset, temperature.background, temperature.minimum), (300.0, 300.0, 0.0))

    def test_files_are_numbered_from_one(self):
        self.assertEqual(ve.frame_file(1), 'fluxfx_00001.vdb')
        self.assertEqual(ve.frame_file(10000), 'fluxfx_10000.vdb')
        for bad in (0, -3, 100000, 1.0):
            with self.assertRaises(ValueError):
                ve.frame_file(bad)

    def test_sequence_maps_first_baked_frame_to_file_one(self):
        self.assertEqual(ve.volume_sequence(-12, 40), dict(is_sequence=True, frame_start=-12, frame_duration=40,
                                                           frame_offset=0, sequence_mode='CLIP'))

    def test_transform_places_voxel_centres_in_the_domain_box(self):
        matrix = ve.index_transform((16, 8, 4))

        def world(i, j, k):  # row vector [i j k 1] times matrix
            return tuple(i * matrix[0][a] + j * matrix[1][a] + k * matrix[2][a] + matrix[3][a] for a in range(3))
        self.assertEqual(world(0, 0, 0), (0.5 / 16 - 0.5, 0.5 / 8 - 0.5, 0.5 / 4 - 0.5))
        self.assertEqual(world(15, 7, 3), (0.5 - 0.5 / 16, 0.5 - 0.5 / 8, 0.5 - 0.5 / 4))


@unittest.skipIf(np is None, 'NumPy not installed')
class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / 'vdb'
        self.shape = (4, 3, 2)
        count = 24
        self.fields = {'DENSITY': np.arange(count, dtype=np.float32) / 10,
                       'TEMPERATURE': np.linspace(-400, 100, count, dtype=np.float32),
                       'FLAME': np.zeros(count, dtype=np.float32), 'FUEL': np.ones(count, dtype=np.float32)}

    def tearDown(self):
        self.temp.cleanup()

    def writer(self, vdb, start=5, end=7):
        return ve.VDBSequenceWriter(self.folder, self.shape, list(self.fields), start, end, 24, vdb,
                                    source={'cache': 'x'}, ambient=293.15)

    def test_array_orientation_is_x_y_z(self):
        flat = np.zeros(24, dtype=np.float32)
        flat[3 + 4 * (2 + 3 * 1)] = 7.0  # x=3, y=2, z=1 in x-fast storage
        xyz = ve.grid_array(flat, self.shape, ve.plan_grids(('DENSITY',))[0])
        self.assertEqual(xyz.shape, (4, 3, 2))
        self.assertTrue(xyz.flags['C_CONTIGUOUS'])
        self.assertEqual(xyz[3, 2, 1], 7.0)
        self.assertEqual(float(xyz.sum()), 7.0)

    def test_frames_write_exact_values_and_manifest(self):
        vdb = FakeVDB()
        writer = self.writer(vdb)
        for frame in (5, 6, 7):
            writer.write(frame, self.fields)
        writer.finish()
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ['export.json', 'fluxfx_00001.vdb', 'fluxfx_00002.vdb', 'fluxfx_00003.vdb'])
        grids = {g.name: g for g in vdb.written[0][1]}
        self.assertEqual(list(grids), ['density', 'heat', 'temperature', 'flame', 'fuel'])
        density = grids['density'].array
        self.assertEqual(density[1, 2, 1], self.fields['DENSITY'][1 + 4 * (2 + 3 * 1)])
        heat, absolute = grids['heat'].array, grids['temperature'].array
        self.assertTrue(np.array_equal(absolute, np.maximum(heat + np.float32(293.15), 0)))
        self.assertEqual(float(absolute.min()), 0.0)  # -400 K excess clamps at 0 K
        self.assertEqual(grids['temperature'].background, 293.15)
        self.assertEqual(grids['density'].gridClass, 'FOG_VOLUME')
        self.assertEqual(grids['density'].transform, ('linear', tuple(tuple(r) for r in ve.index_transform(self.shape))))
        self.assertEqual(grids['density'].tolerance, 0.0)
        manifest = ve.read_manifest(self.folder)
        self.assertEqual(manifest['status'], 'COMPLETE')
        self.assertEqual(manifest['frames']['7']['file'], 'fluxfx_00003.vdb')
        self.assertEqual(manifest['ranges']['flame'], {'min': 0.0, 'max': 0.0})
        self.assertAlmostEqual(manifest['ranges']['density']['max'], 2.3, places=5)
        self.assertEqual(vdb.written[2][2], {'fluxfx_frame': 7, 'fluxfx_format': ve.FORMAT})

    def test_frames_must_be_in_order(self):
        writer = self.writer(FakeVDB())
        with self.assertRaises(ValueError):
            writer.write(6, self.fields)
        writer.write(5, self.fields)
        with self.assertRaises(ValueError):
            writer.write(5, self.fields)

    def test_failed_write_leaves_no_partial_file_and_keeps_prefix(self):
        writer = self.writer(FakeVDB(fail_on=1))
        writer.write(5, self.fields)
        with self.assertRaises(RuntimeError):
            writer.write(6, self.fields)
        writer.finish('FAILED', 'disk full')
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['export.json', 'fluxfx_00001.vdb'])
        manifest = ve.read_manifest(self.folder)
        self.assertEqual((manifest['status'], list(manifest['frames'])), ('FAILED', ['5']))

    def test_manifest_validation_rejects_gaps_and_foreign_formats(self):
        writer = self.writer(FakeVDB())
        writer.write(5, self.fields)
        writer.finish()
        path = self.folder / 'export.json'
        meta = json.loads(path.read_text())
        meta['frames']['7'] = meta['frames'].pop('5')
        path.write_text(json.dumps(meta))
        with self.assertRaises(ValueError):
            ve.read_manifest(self.folder)
        path.write_text(json.dumps(dict(meta, format='other')))
        with self.assertRaises(ValueError):
            ve.read_manifest(self.folder)


if __name__ == '__main__':
    unittest.main()
