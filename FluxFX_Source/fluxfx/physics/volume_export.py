"""Baked frames to an OpenVDB sequence for Cycles/EEVEE; no Blender imports.

Each baked frame becomes one `.vdb` file of float32 FogVolume grids named for
Blender's volume conventions. Raw FluxFX fields are written unchanged; one
derived grid gives absolute temperature for standard blackbody shading:

    density      DENSITY             FluxFX density units
    heat         TEMPERATURE         signed temperature excess, K (as simulated)
    temperature  TEMPERATURE + T0    absolute temperature, K, clamped at 0
    flame        FLAME               fuel burned per second (combustion rate)
    fuel         FUEL                unburned fuel

Files are numbered 1..N (`fluxfx_00001.vdb`, ...) so a Blender Volume with
`frame_start` = first baked frame maps every scene frame to its file, also for
negative frame numbers. Voxel (i, j, k) is FluxFX cell (x, y, z); the grid
transform places voxel centres in the domain object's [-0.5, 0.5]^3 box, so a
Volume parented to the domain lines up with the viewport preview. Zero-valued
voxels (ambient for `temperature`) stay inactive, keeping files sparse.

The OpenVDB Python module is injected (Blender bundles one as `openvdb`), which
keeps this module importable and testable without Blender or OpenVDB. NumPy is
required to export (Blender bundles it).
"""
from dataclasses import asdict, dataclass
from math import prod
import os
from pathlib import Path

from .cache import atomic_json, field_bytes

FORMAT = 'fluxfx-vdb-1'
AMBIENT_KELVIN = 293.15
PREFIX = 'fluxfx_'
DIGITS = 5          # caches hold at most 10,000 frames
MANIFEST = 'export.json'
STATUSES = ('EXPORTING', 'COMPLETE', 'CANCELLED', 'FAILED')


@dataclass(frozen=True)
class GridPlan:
    name: str
    channel: str
    units: str
    description: str
    offset: float = 0.0       # exported value = cached value + offset
    background: float = 0.0   # value of inactive voxels
    minimum: float = None     # clamp after the offset, when set


def plan_grids(channels, ambient=AMBIENT_KELVIN):
    """Grids exported for the cached channels, in a stable order."""
    plan = []
    if 'DENSITY' in channels:
        plan.append(GridPlan('density', 'DENSITY', 'density units', 'Smoke density'))
    if 'TEMPERATURE' in channels:
        plan.append(GridPlan('heat', 'TEMPERATURE', 'K above ambient', 'Simulated signed temperature excess'))
        plan.append(GridPlan('temperature', 'TEMPERATURE', 'K', 'Absolute temperature: ambient + heat, clamped at 0 K',
                             offset=ambient, background=ambient, minimum=0.0))
    if 'FLAME' in channels:
        plan.append(GridPlan('flame', 'FLAME', 'fuel/s', 'Combustion rate: fuel burned per second'))
    if 'FUEL' in channels:
        plan.append(GridPlan('fuel', 'FUEL', 'fuel units', 'Unburned fuel'))
    return tuple(plan)


def frame_file(index):
    """Sequence file for 1-based index `index`."""
    if type(index) is not int or not 1 <= index < 10 ** DIGITS:
        raise ValueError('Sequence index must be 1..99999')
    return f'{PREFIX}{index:0{DIGITS}d}.vdb'


def volume_sequence(start, count):
    """Blender Volume settings mapping scene frame start+k to file k+1."""
    return dict(is_sequence=True, frame_start=start, frame_duration=count, frame_offset=0, sequence_mode='CLIP')


def index_transform(shape):
    """OpenVDB 4x4 (row vectors, translation last): voxel centres -> [-0.5, 0.5]^3."""
    sx, sy, sz = (1.0 / n for n in shape)
    return [[sx, 0.0, 0.0, 0.0], [0.0, sy, 0.0, 0.0], [0.0, 0.0, sz, 0.0],
            [0.5 * sx - 0.5, 0.5 * sy - 0.5, 0.5 * sz - 0.5, 1.0]]


def grid_array(values, shape, entry):
    """Cached x-fast field -> contiguous float32 [x][y][z] array for copyFromArray."""
    import numpy as np
    flat = np.frombuffer(field_bytes(values, prod(shape)), dtype=np.float32)
    xyz = np.ascontiguousarray(flat.reshape(shape[2], shape[1], shape[0]).transpose(2, 1, 0))
    if entry.offset:
        xyz += np.float32(entry.offset)
    if entry.minimum is not None:
        np.maximum(xyz, np.float32(entry.minimum), out=xyz)
    return xyz


class VDBSequenceWriter:
    """Writes frames in order; publishes `export.json` atomically after each."""
    def __init__(self, folder, shape, channels, start, end, fps, vdb, *, source=None,
                 ambient=AMBIENT_KELVIN, producer='FluxFX'):
        if not channels or end < start:
            raise ValueError('Nothing to export')
        self.vdb, self.shape, self.start = vdb, tuple(shape), start
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.plan = plan_grids(channels, ambient)
        if not self.plan:
            raise ValueError('No exportable channels')
        self.matrix = index_transform(self.shape)
        self.meta = dict(format=FORMAT, producer=producer, shape=list(self.shape), start=start, end=end, fps=fps,
                         ambient_kelvin=ambient, transform=self.matrix, file_pattern=f'{PREFIX}{"#" * DIGITS}.vdb',
                         grids=[asdict(entry) for entry in self.plan], source=source or {},
                         status='EXPORTING', message='', frames={}, ranges={})
        self.publish()

    @property
    def path(self):
        return self.folder

    def publish(self):
        atomic_json(self.folder / MANIFEST, self.meta)

    def write(self, frame, fields):
        if self.meta['status'] != 'EXPORTING':
            raise ValueError('VDB export is closed')
        index = frame - self.start + 1
        if index != len(self.meta['frames']) + 1 or frame > self.meta['end']:
            raise ValueError('VDB frames must be written once, in order')
        grids, record = [], dict(file=frame_file(index), grids={})
        for entry in self.plan:
            values = grid_array(fields[entry.channel], self.shape, entry)
            grid = self.vdb.FloatGrid(entry.background)
            grid.copyFromArray(values, tolerance=0.0)
            grid.name = entry.name
            grid.gridClass = self.vdb.GridClass.FOG_VOLUME
            grid.transform = self.vdb.createLinearTransform(self.matrix)
            low, high = float(values.min()), float(values.max())
            record['grids'][entry.name] = dict(min=low, max=high, active_voxels=int(grid.activeVoxelCount()))
            span = self.meta['ranges'].setdefault(entry.name, dict(min=low, max=high))
            span['min'], span['max'] = min(span['min'], low), max(span['max'], high)
            grids.append(grid)
        target = self.folder / record['file']
        temp = target.with_name(target.name + '.partial')
        try:
            self.vdb.write(str(temp), grids=grids, metadata={'fluxfx_frame': int(frame), 'fluxfx_format': FORMAT})
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()
        record['bytes'] = target.stat().st_size
        self.meta['frames'][str(frame)] = record
        self.publish()
        return target

    def finish(self, status='COMPLETE', message=''):
        if status not in STATUSES[1:]:
            raise ValueError('Invalid export status')
        self.meta.update(status=status, message=message)
        self.publish()


def read_manifest(folder):
    """Validated export manifest of a VDB sequence folder."""
    import json
    path = Path(folder) / MANIFEST
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('VDB export manifest too large')
    meta = json.loads(path.read_text())
    if meta.get('format') != FORMAT:
        raise ValueError('Unsupported VDB export format')
    if meta.get('status') not in STATUSES:
        raise ValueError('Invalid VDB export status')
    frames = meta.get('frames')
    expected = [str(meta['start'] + i) for i in range(len(frames or {}))]
    if not isinstance(frames, dict) or sorted(frames, key=int) != expected:
        raise ValueError('VDB export frames are not one contiguous run from the first frame')
    for index, frame in enumerate(expected, start=1):
        if frames[frame].get('file') != frame_file(index):
            raise ValueError('VDB export file numbering is inconsistent')
    return meta
