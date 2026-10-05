import unittest
from fluxfx.blender import invalidation


class FakeProp:
    def __init__(self, identifier, kind='FLOAT', is_array=False):
        self.identifier, self.type, self.is_array = identifier, kind, is_array


class FakeRNA:
    def __init__(self, props):
        self.properties = props


class FakeID:
    def __init__(self, pointer, parent=None, data=None):
        self.pointer, self.parent, self.data = pointer, parent, data

    def as_pointer(self):
        return self.pointer


class FakeGroup:
    """Mimics a PropertyGroup: bl_rna.properties + attribute access."""
    def __init__(self, **values):
        kinds = {'emitter_object': 'POINTER', 'domain_object': 'POINTER', 'collider_object': 'POINTER',
                 'extra_emitters': 'COLLECTION', 'colliders': 'COLLECTION'}
        self.__dict__.update(values)
        self.bl_rna = FakeRNA([FakeProp(name, kinds.get(name, 'FLOAT'), isinstance(value, list))
                               for name, value in values.items()])


class FakeScene:
    def __init__(self, props, fps=24):
        self.fluxfx = props
        self.render = type('Render', (), {'fps': fps, 'fps_base': 1.0})()


def make_scene():
    domain = FakeID(1)
    emitter = FakeID(2, parent=domain, data=None)
    collider = FakeID(3, data=FakeID(30))
    props = FakeGroup(source_rate=2.0, source_center=[0.5, 0.5, 0.16], exposure=3.0,
                      domain_object=domain, emitter_object=emitter,
                      extra_emitters=[FakeGroup(emitter_object=FakeID(4, parent=domain), source_rate=1.0, expanded=False)],
                      colliders=[FakeGroup(collider_object=collider)])
    return FakeScene(props)


class InvalidationTests(unittest.TestCase):
    def setUp(self):
        invalidation.watch(())

    def test_only_watched_ids_scene_and_actions_count_as_edits(self):
        invalidation.watch({7})
        start = invalidation.edits()
        self.assertFalse(invalidation.note_updates([('Object', 99), ('Image', 7000)]))
        self.assertEqual(invalidation.edits(), start)
        self.assertTrue(invalidation.note_updates([('Object', 99), ('Object', 7)]))
        self.assertTrue(invalidation.note_updates([('Action', 5)]))
        self.assertTrue(invalidation.note_updates([('Scene', 6)]))
        self.assertEqual(invalidation.edits(), start + 3)

    def test_watched_ids_follow_parents_and_data(self):
        self.assertEqual(invalidation.watched_ids(make_scene()), {1, 2, 3, 30, 4})

    def test_props_key_ignores_display_only_properties(self):
        scene = make_scene()
        key = invalidation.props_key(scene)
        scene.fluxfx.exposure = 9.0
        scene.fluxfx.extra_emitters[0].expanded = True
        self.assertEqual(invalidation.props_key(scene), key)
        scene.fluxfx.source_rate = 3.0
        self.assertNotEqual(invalidation.props_key(scene), key)

    def test_props_key_tracks_vectors_pointers_entries_and_fps(self):
        scene = make_scene()
        key = invalidation.props_key(scene)
        scene.fluxfx.source_center[2] = 0.3
        self.assertNotEqual(invalidation.props_key(scene), key)
        key = invalidation.props_key(scene)
        scene.fluxfx.emitter_object = None
        self.assertNotEqual(invalidation.props_key(scene), key)
        key = invalidation.props_key(scene)
        scene.fluxfx.extra_emitters[0].source_rate = 4.0
        self.assertNotEqual(invalidation.props_key(scene), key)
        key = invalidation.props_key(scene)
        scene.render.fps = 30
        self.assertNotEqual(invalidation.props_key(scene), key)


class MemoTests(unittest.TestCase):
    def test_idle_ticks_never_recompute(self):
        memo, calls = invalidation.Memo(), []
        for _ in range(1000):
            self.assertTrue(memo.get(('s', 1), 10, lambda: calls.append(1) or True))
        self.assertEqual(len(calls), 1)

    def test_each_new_frame_once_then_free_until_the_stamp_changes(self):
        memo, calls = invalidation.Memo(), []
        compute = lambda: calls.append(1) or True
        for _ in range(3):  # three loops of a 5-frame timeline
            for frame in range(5):
                memo.get(('s', 1), frame, compute)
        self.assertEqual(len(calls), 5)
        memo.get(('s', 2), 0, compute)  # an edit invalidates everything
        self.assertEqual(len(calls), 6)
        self.assertEqual(memo.computed, 6)

    def test_errors_are_cached_until_the_stamp_changes(self):
        memo, calls = invalidation.Memo(), []

        def failing():
            calls.append(1)
            raise ValueError('Animated bake supports direct keyframes')
        for _ in range(5):
            with self.assertRaisesRegex(ValueError, 'direct keyframes'):
                memo.get(('s', 1), 'animation', failing)
        self.assertEqual(len(calls), 1)
        self.assertTrue(memo.get(('s', 2), 'animation', lambda: True))

    def test_reset_forgets_everything(self):
        memo = invalidation.Memo()
        memo.get(('s', 1), 0, lambda: False)
        memo.reset()
        self.assertTrue(memo.get(('s', 1), 0, lambda: True))


if __name__ == '__main__':
    unittest.main()
