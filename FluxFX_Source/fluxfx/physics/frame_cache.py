"""Main-thread decoded-frame LRU. No Blender state, GPU work or worker threads."""
from collections import OrderedDict
from math import prod


class FrameCache:
    def __init__(self, reader, limit_bytes):
        self.reader = reader
        self.frame_bytes = prod(reader.grid.shape) * 4 * len(reader.meta['channels'])
        self.entries = OrderedDict()
        self.hits = self.misses = 0
        self.configure(limit_bytes)

    @property
    def used_bytes(self): return len(self.entries) * self.frame_bytes

    @property
    def capacity(self): return self.limit_bytes // self.frame_bytes

    def configure(self, limit_bytes):
        if type(limit_bytes) is not int or limit_bytes < 0:
            raise ValueError('Frame memory limit must be a nonnegative integer')
        self.limit_bytes = limit_bytes
        while self.used_bytes > self.limit_bytes: self.entries.popitem(last=False)

    def clear(self): self.entries.clear()

    def token(self, frame):
        if type(frame) is not int or str(frame) not in self.reader.meta['frames']:
            raise ValueError(f'Frame {frame} is not baked')
        stat = (self.reader.path / f'frame_{frame}.fxc').stat()
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def current(self, frame):
        """Check an entry without returning its data or changing its LRU order."""
        entry = self.entries.get(frame)
        if entry is None: return False
        try: valid = self.token(frame) == entry[0]
        except OSError:
            self.entries.pop(frame, None)
            raise
        if not valid: self.entries.pop(frame, None)
        return valid

    def get(self, frame):
        try: before = self.token(frame)
        except (ValueError, OSError):
            self.entries.pop(frame, None)
            raise
        entry = self.entries.pop(frame, None)
        if entry is not None and entry[0] == before:
            self.entries[frame] = entry
            self.hits += 1
            return entry[1], True
        self.misses += 1
        fields = self.reader.read(frame)
        if self.token(frame) != before:
            raise ValueError('Cache frame changed while reading; load the cache again')
        if self.capacity:
            while len(self.entries) >= self.capacity: self.entries.popitem(last=False)
            self.entries[frame] = (before, fields)
        return fields, False

    def upcoming(self, frame, direction=1, count=2):
        """Leave room for the displayed frame; never prefetch unbaked frames."""
        count = min(count, max(0, self.capacity - 1))
        return [f for i in range(1, count + 1)
                if str(f := frame + i * direction) in self.reader.meta['frames']]
