import json
from pathlib import Path
import tempfile
import unittest
from fluxfx.physics.cache import CacheWriter,CacheReader,estimate_bytes,fingerprint,validate_range
from fluxfx.physics.config import GridSpec


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.grid=GridSpec((2,3,4));self.signature=fingerprint({'test':1})
    def tearDown(self):self.temp.cleanup()
    def writer(self):return CacheWriter(self.temp.name,self.grid,['DENSITY','TEMPERATURE'],1,2,24,self.signature)
    def fields(self):return {'DENSITY':[.5]*24,'TEMPERATURE':[-2.]*24}
    def test_roundtrip_and_channels(self):
        w=self.writer();w.write(1,self.fields());w.write(2,self.fields());w.finish()
        r=CacheReader(w.path);self.assertEqual(r.grid,self.grid)
        self.assertEqual(list(r.read(2)['TEMPERATURE']),[-2.]*24)
        self.assertEqual(r.meta['status'],'COMPLETE')
    def test_partial_cancel(self):
        w=self.writer();w.write(1,self.fields());w.finish('CANCELLED')
        r=CacheReader(w.path);self.assertEqual(len(r.read(1)['DENSITY']),24)
        with self.assertRaises(ValueError):r.read(2)
    def test_isolated_bakes(self):self.assertNotEqual(self.writer().path,self.writer().path)
    def test_order_and_completion(self):
        w=self.writer()
        with self.assertRaises(ValueError):w.write(2,self.fields())
        with self.assertRaises(ValueError):w.finish()
        w.write(1,self.fields())
        with self.assertRaises(ValueError):w.write(1,self.fields())
    def test_invalid_fields_do_not_publish(self):
        w=self.writer()
        for data in ([float('nan')]*24,[-1.]*24,[1.]):
            with self.assertRaises(ValueError):w.write(1,dict(self.fields(),DENSITY=data))
        self.assertEqual(CacheReader(w.path).meta['frames'],{})
        self.assertFalse((w.path/'frame_1.fxc').exists())
    def test_corruption(self):
        w=self.writer();w.write(1,self.fields());p=w.path/'frame_1.fxc'
        raw=bytearray(p.read_bytes());raw[0]^=1;p.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'checksum'):CacheReader(w.path).read(1)
        p.write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'size'):CacheReader(w.path).read(1)
    def test_manifest_validation(self):
        w=self.writer();p=w.path/'manifest.json';m=w.meta.copy();m['frames']={'../../bad':{}}
        p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):CacheReader(w.path)
    def test_estimate_and_range(self):
        self.assertGreater(estimate_bytes((64,)*3,['DENSITY','TEMPERATURE'],1,120),64**3*8*120)
        for args in [(2,1,24),(1,10001,24),(1,2,0)]:
            with self.assertRaises(ValueError):validate_range(*args)
    def test_fingerprint_order_and_changes(self):
        self.assertEqual(fingerprint(dict(a=1,b=2)),fingerprint(dict(b=2,a=1)))
        self.assertNotEqual(fingerprint(dict(a=1)),fingerprint(dict(a=2)))
    def test_animated_manifest_requires_inputs(self):
        w=self.writer();w.write(1,self.fields());w.meta['provenance']={'mode':'ANIMATED_INPUTS','inputs':{}}
        w.publish()
        with self.assertRaises(ValueError):CacheReader(w.path)
        w.meta['provenance']['inputs']['1']=self.signature;w.publish()
        self.assertEqual(CacheReader(w.path).read(1)['DENSITY'][0],.5)
    def test_closed_writer(self):
        w=self.writer();w.finish('CANCELLED')
        with self.assertRaises(ValueError):w.write(1,self.fields())

if __name__=='__main__':unittest.main()
