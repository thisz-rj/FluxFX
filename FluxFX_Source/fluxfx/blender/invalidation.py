"""Cheap change tracking, so cache validation never fingerprints an idle scene.

A full input fingerprint (evaluated transforms, mesh snapshots, JSON + SHA-256
and, for animated caches, every keyframe) is only needed after something that
feeds the simulation changed. Two cheap signals cover every input:

- `depsgraph_update_post` naming a watched ID (domain, emitters, colliders,
  their parents and data), the Scene or an Action. Verified in Blender 5.2:
  object, parent, modifier-input and mesh edits report the affected IDs and
  keyframe edits report the Action; frame changes do not fire this handler.
- `props_key`: FluxFX property values plus scene FPS, compared on every check,
  because edits to Python-defined properties do not tag the depsgraph.

Their combination is the `stamp`; results are memoised per frame until it
changes. Importable without Blender so the policy is unit-tested.
"""

# Properties that cannot change a simulation input or cache fingerprint.
DISPLAY_ONLY = frozenset({
    'rna_type', 'name', 'expanded',
    'preview_mode', 'preview_channel', 'show_preview', 'slice_y', 'exposure', 'ray_steps',
    'playback_budget_ms',
    'cache_directory', 'cache_path', 'cache_start', 'cache_end', 'cache_animated',
    'cache_compress', 'cache_memory_mb', 'cache_prefetch',
    'native_budget_mb', 'native_status',
    'sparse_grid', 'sparse_capacity', 'sparse_linger', 'sparse_halo', 'sparse_speed_margin',
    'vdb_during_bake', 'render_auto_volume', 'render_ambient', 'render_density', 'render_smoke_color',
    'render_fire_mode', 'render_flame_temperature', 'render_flame_reference', 'render_fire_intensity',
})
ALWAYS_RELEVANT = frozenset({'Scene', 'Action'})

_edits = 0
_watched = frozenset()


def edits():
    """Generation counter; increases whenever a watched input may have changed."""
    return _edits


def watch(pointers):
    global _watched
    _watched = frozenset(pointers)


def note_updates(updates):
    """Bump the generation for (type name, original ID pointer) pairs that matter."""
    global _edits
    for kind, pointer in updates:
        if kind in ALWAYS_RELEVANT or pointer in _watched:
            _edits += 1
            return True
    return False


def depsgraph_updated(_scene, depsgraph):
    """depsgraph_update_post handler (made persistent at registration)."""
    note_updates((type(update.id).__name__, update.id.original.as_pointer())
                 for update in depsgraph.updates)


def watched_ids(scene):
    """Pointers of every ID whose evaluated state feeds the simulation."""
    props = scene.fluxfx
    roots = [props.domain_object, props.emitter_object]
    roots += [entry.emitter_object for entry in props.extra_emitters]
    roots += [entry.collider_object for entry in props.colliders]
    found = set()
    for obj in roots:
        while obj is not None and obj.as_pointer() not in found:
            found.add(obj.as_pointer())
            if getattr(obj, 'data', None) is not None:
                found.add(obj.data.as_pointer())
            obj = obj.parent
    return found


def group_key(group):
    """Hashable snapshot of a PropertyGroup's input properties (no collections)."""
    values = []
    for prop in group.bl_rna.properties:
        name = prop.identifier
        if name in DISPLAY_ONLY or prop.type == 'COLLECTION':
            continue
        value = getattr(group, name)
        if prop.type == 'POINTER':
            value = value.as_pointer() if value is not None else 0
        elif getattr(prop, 'is_array', False):
            value = tuple(value)
        values.append(value)
    return tuple(values)


def props_key(scene):
    props = scene.fluxfx
    return (scene.render.fps, scene.render.fps_base, group_key(props),
            tuple(group_key(entry) for entry in props.extra_emitters),
            tuple(group_key(entry) for entry in props.colliders))


def stamp(scene):
    return edits(), props_key(scene)


class Memo:
    """Results per key, discarded when the stamp changes.

    Exceptions are memoised as well: a persistent problem (a constraint on an
    animated emitter, a missing object) is reported every tick without being
    recomputed every tick.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.stamp = object()
        self.entries = {}
        self.computed = 0

    def get(self, stamp, key, compute):
        if stamp != self.stamp:
            self.stamp, self.entries = stamp, {}
        if key not in self.entries:
            self.computed += 1
            try:
                self.entries[key] = (True, compute())
            except Exception as exc:
                self.entries[key] = (False, exc)
        ok, value = self.entries[key]
        if not ok:
            raise value.with_traceback(None)
        return value
