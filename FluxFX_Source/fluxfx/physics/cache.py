"""Portable, bounded, atomic playback cache; no Blender or GPU dependency."""
from array import array
from hashlib import sha256
from math import isfinite, prod
from pathlib import Path
import json
import os
import sys
from uuid import uuid4
from zlib import crc32, compressobj, decompressobj, error as ZlibError
from .config import GridSpec

FORMAT = 'fluxfx-playback-1'
COMPRESSED_FORMAT = 'fluxfx-playback-2'
ENCODINGS = ('RAW', 'AUTO_ZLIB')
CHANNELS = ('DENSITY', 'TEMPERATURE', 'FUEL', 'FLAME', 'COLLISION')
try:
    import numpy as np  # Blender bundles NumPy; standalone format tools can omit it.
except ImportError:
    np = None


def float32_view(values, count=None):
    """Flat float32 memoryview of a buffer-protocol object, without copying.

    Accepts gpu.types.Buffer readbacks, NumPy float32 arrays, array('f') and
    memoryviews. Returns None for anything else (a list, float64 data,
    non-contiguous memory) so callers can convert explicitly.
    """
    try:
        view = memoryview(values)
    except TypeError:
        return None
    native = view.format in ('f', '@f', '=f') or (view.format == '<f' and sys.byteorder == 'little')
    if not native or view.itemsize != 4 or not view.c_contiguous:
        return None
    flat = view.cast('B').cast('f')
    if count is not None and len(flat) != count:
        raise ValueError('Wrong field size')
    return flat


def field_bytes(values, count):
    """Little-endian float32 field as a bytes-like view; copies only when it must."""
    view = float32_view(values, count)
    if view is None:
        if np is not None and isinstance(values, np.ndarray):
            view = float32_view(np.ascontiguousarray(values, dtype=np.float32).ravel(), count)
        else:
            if len(values) != count: raise ValueError('Wrong field size')
            view = memoryview(array('f', values))
    if sys.byteorder != 'little':
        swapped = array('f', view); swapped.byteswap(); view = memoryview(swapped)
    return view


def valid_field(data, channel):
    if np is not None:
        values = np.frombuffer(data, dtype=np.float32)
        return bool(np.isfinite(values).all() and (channel == 'TEMPERATURE' or (values >= 0).all()))
    return all(isfinite(v) and (channel == 'TEMPERATURE' or v >= 0) for v in data)


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_range(start, end, fps):
    if type(start) is not int or type(end) is not int or not -1048574 <= start <= end <= 1048574 or end-start >= 10000:
        raise ValueError('Use an ordered range of at most 10,000 frames')
    if not isfinite(fps) or not 0 < fps <= 1000:
        raise ValueError('Invalid cache frame rate')


def estimate_bytes(shape, channels, start, end):
    GridSpec(tuple(shape))
    validate_range(start, end, 24)
    if not channels or len(set(channels)) != len(channels) or any(c not in CHANNELS for c in channels):
        raise ValueError('Invalid cache channels')
    # Raw float32 fields plus conservative allowance for manifest/filesystem overhead.
    return (prod(shape)*4*len(channels)+4096)*(end-start+1)+65536


def atomic_json(path, value):
    temp = path.with_name(path.name+'.tmp')
    try:
        with temp.open('w') as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        if temp.exists(): temp.unlink()


class CacheWriter:
    def __init__(self, parent, grid, channels, start, end, fps, signature, provenance=None, encoding='RAW'):
        if encoding not in ENCODINGS: raise ValueError('Unsupported cache encoding')
        validate_range(start, end, fps)
        estimate_bytes(grid.shape, channels, start, end)
        self.path = Path(parent) / ('fluxfx-bake-'+uuid4().hex[:12])
        self.path.mkdir(parents=True, exist_ok=False)
        self.encoding = encoding
        self.meta = dict(format=FORMAT if encoding == 'RAW' else COMPRESSED_FORMAT, shape=list(grid.shape), extent=list(grid.extent),
                         channels=list(channels), start=start, end=end, fps=fps,
                         signature=signature, provenance=provenance or {}, status='BAKING', frames={})
        if encoding != 'RAW': self.meta['encoding'] = encoding
        self.publish()

    def publish(self): atomic_json(self.path/'manifest.json', self.meta)

    def write(self, frame, fields):
        if self.meta['status'] != 'BAKING': raise ValueError('Cache writer is closed')
        if type(frame) is not int or frame != self.meta['start']+len(self.meta['frames']) or frame > self.meta['end']:
            raise ValueError('Cache frames must be written once, in order')
        if set(fields) != set(self.meta['channels']): raise ValueError('Cache channels differ')
        target = self.path / f'frame_{frame}.fxc'
        temp = target.with_suffix('.tmp'); checksum = 0; size = 0
        count = prod(self.meta['shape'])
        held = [] if self.encoding == 'AUTO_ZLIB' else None
        codec = 'RAW'
        try:
            with temp.open('xb') as stream:
                # Fields arrive as GPU readback buffers or arrays: write their
                # memory directly instead of materialising Python lists or bytes.
                for channel in self.meta['channels']:
                    view = field_bytes(fields[channel], count)
                    if not valid_field(view, channel):
                        raise ValueError('Invalid cache field values')
                    checksum = crc32(view, checksum); size += view.nbytes
                    if held is None: stream.write(view)
                    else: held.append(view)
                if held is not None:
                    encoder = compressobj(level=1)
                    encoded = [encoder.compress(view) for view in held]
                    encoded.append(encoder.flush())
                    if sum(len(part) for part in encoded) < size:
                        stream.writelines(encoded); codec = 'ZLIB'
                    else:
                        for view in held: stream.write(view)
                stream.flush(); os.fsync(stream.fileno())
            temp.replace(target)
            record = dict(bytes=target.stat().st_size, crc32=f'{checksum:08x}')
            if self.encoding != 'RAW': record.update(codec=codec, raw_bytes=size)
            self.meta['frames'][str(frame)] = record
            self.publish()
        finally:
            if temp.exists(): temp.unlink()

    def finish(self, status='COMPLETE', message=''):
        if status not in {'COMPLETE', 'CANCELLED', 'FAILED'}: raise ValueError('Invalid cache status')
        if status == 'COMPLETE' and len(self.meta['frames']) != self.meta['end']-self.meta['start']+1:
            raise ValueError('Cannot complete a partial cache')
        self.meta.update(status=status, message=message)
        self.publish()


class CacheReader:
    def __init__(self, path):
        self.path = Path(path)
        manifest = self.path/'manifest.json'
        if manifest.stat().st_size > 4*1024*1024: raise ValueError('Cache manifest too large')
        self.meta = json.loads(manifest.read_text())
        m = self.meta
        if m['format'] not in {FORMAT, COMPRESSED_FORMAT}: raise ValueError('Unsupported playback cache format')
        if m['format'] == COMPRESSED_FORMAT and m.get('encoding') != 'AUTO_ZLIB':
            raise ValueError('Unsupported cache encoding')
        self.grid = GridSpec(tuple(m['shape']), tuple(m['extent']))
        validate_range(m['start'], m['end'], m['fps'])
        estimate_bytes(self.grid.shape, m['channels'], m['start'], m['end'])
        if m['status'] not in {'BAKING','COMPLETE','CANCELLED','FAILED'}: raise ValueError('Invalid cache status')
        if not isinstance(m['signature'], str) or len(m['signature']) != 64: raise ValueError('Invalid cache signature')
        if not isinstance(m['frames'], dict) or len(m['frames']) > m['end']-m['start']+1:
            raise ValueError('Invalid cache frame table')
        expected = {str(f) for f in range(m['start'], m['start']+len(m['frames']))}
        if set(m['frames']) != expected: raise ValueError('Invalid cache frame sequence')
        if m['status'] == 'COMPLETE' and len(expected) != m['end']-m['start']+1:
            raise ValueError('Incomplete cache marked complete')
        provenance=m.get('provenance',{})
        if provenance.get('mode') == 'ANIMATED_INPUTS':
            inputs=provenance.get('inputs',{})
            if not isinstance(inputs,dict) or not expected.issubset(inputs) or any(
                    not isinstance(inputs[f],str) or len(inputs[f])!=64 for f in expected):
                raise ValueError('Animated cache lacks per-frame input signatures')

    def read(self, frame):
        if type(frame) is not int or str(frame) not in self.meta['frames']:
            raise ValueError(f'Frame {frame} is not baked')
        count = prod(self.grid.shape); size = count*4*len(self.meta['channels'])
        record = self.meta['frames'][str(frame)]; path = self.path/f'frame_{frame}.fxc'
        codec = record.get('codec') if self.meta['format'] == COMPRESSED_FORMAT else 'RAW'
        if codec not in {'RAW', 'ZLIB'}: raise ValueError('Unsupported frame encoding')
        stored = record['bytes']
        if type(stored) is not int or not 0 < stored <= size or path.stat().st_size != stored:
            raise ValueError('Cache frame size mismatch')
        if self.meta['format'] == COMPRESSED_FORMAT and record.get('raw_bytes') != size:
            raise ValueError('Cache decoded size mismatch')
        if codec == 'RAW' and stored != size: raise ValueError('Cache frame size mismatch')
        # Bound both the encoded read and decompression before allocating fields.
        with path.open('rb') as stream: raw = stream.read(stored + 1)
        if len(raw) != stored: raise ValueError('Cache frame size mismatch')
        if codec == 'ZLIB':
            try:
                decoder = decompressobj()
                raw = decoder.decompress(raw, size + 1)
                if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise ValueError('Invalid compressed cache frame')
            except ZlibError as exc:
                raise ValueError('Invalid compressed cache frame') from exc
        if f'{crc32(raw):08x}' != record['crc32']: raise ValueError('Cache frame checksum mismatch')
        fields = {}
        whole = memoryview(raw)
        for i, channel in enumerate(self.meta['channels']):
            data = array('f'); data.frombytes(whole[i*count*4:(i+1)*count*4])
            if sys.byteorder != 'little': data.byteswap()
            if not valid_field(data, channel):
                raise ValueError('Invalid cached field')
            fields[channel] = data
        return fields
