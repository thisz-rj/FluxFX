"""Lossless encoding, legacy compatibility and bounded corrupt-frame rejection."""
from array import array
import random
import tempfile
import unittest
from unittest.mock import patch
from zlib import compress, crc32
from fluxfx.physics import cache
from fluxfx.physics.config import GridSpec


class CompressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.grid = GridSpec((8, 8, 8))
        self.fields = {'DENSITY': array('f', [.25]*512), 'TEMPERATURE': array('f', [-2.]*512)}
    def tearDown(self): self.temp.cleanup()
    def writer(self, encoding='AUTO_ZLIB', grid=None):
        return cache.CacheWriter(self.temp.name, grid or self.grid, list(self.fields), 1, 2, 24,
                                 cache.fingerprint({'test': 27}), encoding=encoding)
    def encoded(self):
        w = self.writer(); w.write(1, self.fields)
        return w
    def rewrite(self, w, payload, **record):
        (w.path/'frame_1.fxc').write_bytes(payload)
        w.meta['frames']['1'].update(bytes=len(payload), **record); w.publish()
    def test_lossless_all_bits_and_negative_heat(self):
        w=self.encoded(); w.write(2,self.fields); w.finish()
        r=cache.CacheReader(w.path)
        self.assertEqual(r.meta['format'],cache.COMPRESSED_FORMAT)
        self.assertEqual(r.meta['frames']['1']['codec'],'ZLIB')
        self.assertLess(r.meta['frames']['1']['bytes'],4096)
        for k,v in r.read(2).items(): self.assertEqual(v.tobytes(),self.fields[k].tobytes())
    def test_raw_fallback_for_incompressible_frame(self):
        grid=GridSpec((2,2,2)); rng=random.Random(27)
        # Tiny varied finite float patterns have more stream overhead than savings.
        fields={k:array('f',[rng.random()*100 for _ in range(8)]) for k in self.fields}
        w=self.writer(grid=grid); w.write(1,fields)
        self.assertEqual(w.meta['frames']['1']['codec'],'RAW')
        self.assertEqual(cache.CacheReader(w.path).read(1)['DENSITY'].tobytes(),fields['DENSITY'].tobytes())
    def test_legacy_raw_format_unchanged(self):
        w=self.writer('RAW'); w.write(1,self.fields)
        self.assertEqual(w.meta['format'],cache.FORMAT)
        self.assertNotIn('encoding',w.meta)
        self.assertEqual(set(w.meta['frames']['1']),{'bytes','crc32'})
        self.assertEqual(cache.CacheReader(w.path).read(1)['DENSITY'].tobytes(),self.fields['DENSITY'].tobytes())
    def test_cancelled_prefix_readable(self):
        w=self.encoded(); w.finish('CANCELLED'); r=cache.CacheReader(w.path)
        self.assertEqual(r.read(1)['TEMPERATURE'][0],-2.)
        with self.assertRaises(ValueError):r.read(2)
    def test_truncated_and_trailing_stream_rejected(self):
        for change in (lambda b:b[:-1],lambda b:b+b'extra',lambda b:b+b):
            w=self.encoded(); self.rewrite(w,change((w.path/'frame_1.fxc').read_bytes()))
            with self.assertRaisesRegex(ValueError,'compressed'):cache.CacheReader(w.path).read(1)
    def test_expansion_beyond_declared_grid_rejected(self):
        w=self.encoded();self.rewrite(w,compress(b'\0'*8192))
        with self.assertRaisesRegex(ValueError,'compressed'):cache.CacheReader(w.path).read(1)
    def test_checksum_of_decoded_fields(self):
        w=self.encoded();w.meta['frames']['1']['crc32']='00000000';w.publish()
        with self.assertRaisesRegex(ValueError,'checksum'):cache.CacheReader(w.path).read(1)
    def test_invalid_decoded_values_rejected(self):
        for invalid in (float('nan'),float('inf'),-1.):
            w=self.encoded();raw=array('f',[invalid]*512+[-2.]*512).tobytes()
            self.rewrite(w,compress(raw),crc32=f'{crc32(raw):08x}')
            with self.assertRaisesRegex(ValueError,'field'):cache.CacheReader(w.path).read(1)
    def test_declared_sizes_and_unknown_codecs_rejected(self):
        for record in ({'bytes':True},{'bytes':4097},{'raw_bytes':8192},{'codec':'UNKNOWN'}):
            w=self.encoded();w.meta['frames']['1'].update(record);w.publish()
            with self.assertRaises(ValueError):cache.CacheReader(w.path).read(1)
        w=self.encoded();w.meta['encoding']='UNKNOWN';w.publish()
        with self.assertRaises(ValueError):cache.CacheReader(w.path)
        with self.assertRaises(ValueError):self.writer('UNKNOWN')
    def test_portable_without_numpy(self):
        with patch.object(cache,'np',None):
            w=self.encoded();r=cache.CacheReader(w.path)
            self.assertEqual(r.read(1)['TEMPERATURE'].tobytes(),self.fields['TEMPERATURE'].tobytes())
    def test_failed_compressed_write_preserves_published_prefix(self):
        w=self.encoded()
        with patch.object(cache.os,'fsync',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):w.write(2,self.fields)
        reader=cache.CacheReader(w.path)
        self.assertEqual(set(reader.meta['frames']),{'1'})
        self.assertEqual(reader.read(1)['DENSITY'][0],.25)
        self.assertFalse((w.path/'frame_2.tmp').exists())
        self.assertFalse((w.path/'frame_2.fxc').exists())
    def test_invalid_write_does_not_publish_frame(self):
        w=self.writer()
        with self.assertRaises(ValueError): w.write(1,dict(self.fields,DENSITY=[-1.]*512))
        self.assertEqual(cache.CacheReader(w.path).meta['frames'],{})
        self.assertFalse((w.path/'frame_1.fxc').exists())
        w.write(1,self.fields)
        self.assertEqual(cache.CacheReader(w.path).read(1)['DENSITY'][0],.25)

if __name__=='__main__':unittest.main()
