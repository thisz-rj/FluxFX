"""Per-frame cost of bake readback and cache writing (data copying).

Measures what one baked frame costs between the solver and disk, using the
real device readback and CacheWriter code:

    readback  GPU texture -> CPU field (BlenderGPUDevice.read / read_array)
    write     CacheWriter.write: validation, CRC32, file write and fsync

Two sources:
    graphical or headless Blender with a GPU context (real texture.read):
        blender --python scripts/bake_copy_benchmark.py -- --grid 128
    plain Python (simulated readback buffer, no Blender):
        python3 scripts/bake_copy_benchmark.py --grid 128

`legacy` converts through Python lists (0.41 behaviour); `fast` uses the
zero-copy buffer path when the device provides `read_array`.
"""
import argparse
from array import array
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fluxfx.physics.cache import CacheWriter, fingerprint  # noqa: E402
from fluxfx.physics.config import GridSpec  # noqa: E402

CHANNELS = ('DENSITY', 'TEMPERATURE', 'FUEL', 'FLAME', 'COLLISION')


class SimulatedBuffer(array):
    """Stands in for gpu.types.Buffer: buffer protocol, iteration, dimensions."""
    dimensions = None


class SimulatedTexture:
    def __init__(self, values):
        self.values = values

    def read(self):
        # A real readback also allocates and fills a fresh CPU buffer.
        return SimulatedBuffer('f', self.values)


def field(n, seed):
    count = n ** 3
    return array('f', (((i * 2654435761 + seed) % 1000) / 1000.0 for i in range(count)))


def textures(n, use_gpu):
    data = {name: field(n, i) for i, name in enumerate(CHANNELS)}
    if not use_gpu:
        return None, {name: SimulatedTexture(values) for name, values in data.items()}
    import gpu
    from fluxfx.backend.device import BlenderGPUDevice
    device = BlenderGPUDevice()
    made = {}
    for name, values in data.items():
        buffer = gpu.types.Buffer('FLOAT', len(values), values)
        made[name] = gpu.types.GPUTexture((n, n, n), format='R32F', data=buffer)
    return device, made


def run(mode, device_read, textures_by_name, grid, frames, folder):
    writer = CacheWriter(folder, grid, list(CHANNELS), 0, frames - 1, 24, fingerprint({'bench': mode}))
    readback, write = [], []
    for frame in range(frames):
        start = time.perf_counter()
        fields = {name: device_read(texture, grid.shape) for name, texture in textures_by_name.items()}
        middle = time.perf_counter()
        writer.write(frame, fields)
        end = time.perf_counter()
        readback.append((middle - start) * 1000)
        write.append((end - middle) * 1000)
        del fields
    writer.finish()
    return dict(readback_ms=statistics.median(readback), write_ms=statistics.median(write),
                total_ms=statistics.median(r + w for r, w in zip(readback, write)))


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--grid', type=int, default=128)
    parser.add_argument('--frames', type=int, default=3)
    parser.add_argument('--simulated', action='store_true', help='no GPU even inside Blender')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        import gpu  # noqa: F401
        use_gpu = not args.simulated
    except ImportError:
        use_gpu = False
    from fluxfx.backend.device import BlenderGPUDevice
    device, made = textures(args.grid, use_gpu)
    grid = GridSpec((args.grid,) * 3)
    modes = {'legacy': BlenderGPUDevice.read}
    if hasattr(BlenderGPUDevice, 'read_array'):
        modes['fast'] = BlenderGPUDevice.read_array
    report = dict(grid=args.grid, channels=len(CHANNELS), frames=args.frames,
                  frame_mib=args.grid ** 3 * 4 * len(CHANNELS) / 2 ** 20,
                  source='gpu texture.read' if use_gpu else 'simulated buffer', results={})
    with tempfile.TemporaryDirectory() as folder:
        for mode, read in modes.items():
            report['results'][mode] = run(mode, read, made, grid, args.frames, folder)
            print(mode, {k: round(v, 1) for k, v in report['results'][mode].items()}, flush=True)
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:])
