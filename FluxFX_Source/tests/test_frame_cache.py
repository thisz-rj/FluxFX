import tempfile
import unittest
from unittest.mock import patch
from fluxfx.physics.cache import CacheWriter,CacheReader,fingerprint
from fluxfx.physics.config import GridSpec
from fluxfx.physics.frame_cache import FrameCache


class FrameCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        w=CacheWriter(self.temp.name,GridSpec((2,2,2)),['DENSITY'],1,5,24,fingerprint({}),encoding='AUTO_ZLIB')
        for f in range(1,6):w.write(f,{'DENSITY':[float(f)]*8})
        w.finish();self.reader=CacheReader(w.path);self.pool=FrameCache(self.reader,64)
    def tearDown(self):self.temp.cleanup()
    def test_hit_skips_decode_and_preserves_values(self):
        a,hit=self.pool.get(1);self.assertFalse(hit)
        with patch.object(self.reader,'read',side_effect=AssertionError('unexpected read')):
            b,hit=self.pool.get(1)
        self.assertTrue(hit);self.assertIs(a,b);self.assertEqual(list(b['DENSITY']),[1.]*8)
    def test_lru_eviction_and_bound(self):
        for f in (1,2,1,3):self.pool.get(f)
        self.assertEqual(list(self.pool.entries),[1,3]);self.assertEqual(self.pool.used_bytes,64)
        self.assertFalse(self.pool.get(2)[1]);self.assertLessEqual(self.pool.used_bytes,64)
    def test_reduce_limit_zero_and_oversize(self):
        self.pool.get(1);self.pool.get(2);self.pool.configure(32)
        self.assertEqual(list(self.pool.entries),[2])
        for limit in (0,31):
            self.pool.configure(limit);self.pool.get(3)
            self.assertEqual(self.pool.used_bytes,0)
            self.assertFalse(self.pool.get(3)[1])
    def test_deleted_cached_file_is_not_served(self):
        self.pool.get(1);(self.reader.path/'frame_1.fxc').unlink()
        with self.assertRaises(OSError):self.pool.get(1)
        self.assertEqual(self.pool.used_bytes,0)
    def test_changed_cached_file_is_revalidated(self):
        self.pool.get(1);(self.reader.path/'frame_1.fxc').write_bytes(b'broken')
        with self.assertRaises(ValueError):self.pool.get(1)
        self.assertNotIn(1,self.pool.entries)
    def test_file_changes_during_decode_rejected(self):
        read=self.reader.read
        def changing(frame):
            data=read(frame);(self.reader.path/'frame_1.fxc').write_bytes(b'broken');return data
        with patch.object(self.reader,'read',side_effect=changing):
            with self.assertRaisesRegex(ValueError,'changed'):self.pool.get(1)
        self.assertEqual(self.pool.used_bytes,0)
    def test_prefetch_range_direction_and_capacity(self):
        self.assertEqual(self.pool.upcoming(1),[2]);self.assertEqual(self.pool.upcoming(5),[])
        self.pool.configure(96)
        self.assertEqual(self.pool.upcoming(4,-1),[3,2])
        self.assertEqual(self.pool.upcoming(1,-1),[])
        self.pool.configure(32);self.assertEqual(self.pool.upcoming(1),[])
    def test_clear_releases_references(self):
        self.pool.get(1);self.pool.clear();self.assertEqual(self.pool.used_bytes,0)
        self.assertFalse(self.pool.get(1)[1])
    def test_separate_runs_do_not_share_entries(self):
        self.pool.get(1);other=FrameCache(self.reader,64)
        self.assertFalse(other.get(1)[1])
    def test_invalid_limit_and_missing_frame(self):
        for limit in (-1,1.5,True):
            with self.assertRaises(ValueError):self.pool.configure(limit)
        with self.assertRaises(ValueError):self.pool.get(6)

if __name__=='__main__':unittest.main()
