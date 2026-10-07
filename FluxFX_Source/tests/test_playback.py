import unittest
from fluxfx.physics.playback import PlaybackClock, source_span
from fluxfx.physics.emission import Source, Emission


class FakeClock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class PlaybackTests(unittest.TestCase):
    def test_catches_up_multiple_steps_without_advancing_future(self):
        clock = FakeClock(); playback = PlaybackClock(0)
        clock.now = .033; playback.begin(clock())
        def advance(remaining):
            clock.now += .002
            return min(.01, remaining)
        delay = playback.run(advance, .024, clock)
        self.assertEqual(playback.report['substeps'], 4)
        self.assertAlmostEqual(playback.simulated, .033)
        self.assertAlmostEqual(playback.report['lag_ms'], 8)
        self.assertAlmostEqual(delay, 1/30 - .008)

    def test_completed_work_budget_and_resume_debt(self):
        clock = FakeClock(); playback = PlaybackClock(0)
        clock.now = .1; playback.begin(clock())
        def advance(remaining):
            clock.now += .015
            return min(.01, remaining)
        self.assertEqual(playback.run(advance, .024, clock), .001)
        self.assertEqual(playback.report['substeps'], 2)
        self.assertAlmostEqual(playback.debt, .08)
        self.assertAlmostEqual(playback.report['callback_ms'], 30)
        clock.now += .001; playback.begin(clock())
        self.assertAlmostEqual(playback.debt, .111)

    def test_one_expensive_step_yields_and_step_count_is_bounded(self):
        clock = FakeClock(); playback = PlaybackClock(0); playback.begin(.1)
        def advance(remaining): clock.now += .2; return .001
        playback.run(advance, .001, clock)
        self.assertEqual(playback.report['substeps'], 1)
        playback.run(lambda remaining: .001, .1, clock, max_steps=3)
        self.assertEqual(playback.report['substeps'], 3)

    def test_sleep_discard_is_visible_not_simulated(self):
        playback = PlaybackClock(10)
        self.assertAlmostEqual(playback.begin(20), 9.75)
        self.assertEqual(playback.simulated, 0)
        self.assertEqual(playback.debt, .25)
        self.assertEqual(playback.dropped, 9.75)
        resumed = PlaybackClock(30)
        resumed.begin(30.01)
        self.assertAlmostEqual(resumed.debt, .01)

    def test_invalid_step_rejected_without_accounting(self):
        for dt in (0, -1, float('nan'), .2):
            playback = PlaybackClock(0); playback.begin(.1)
            with self.assertRaises(ValueError): playback.run(lambda _: dt, .02, lambda: .1)
            self.assertEqual(playback.simulated, 0)

    def test_source_path_subdivision_and_rate_preservation(self):
        source = Source((1, .5, .5), .1, 3, 2, Emission((0, .5, .5), (2, 0, 0), 4))
        spans = [source_span(source, i/4, (i+1)/4) for i in range(4)]
        self.assertEqual(spans[0].motion.start, source.motion.start)
        self.assertEqual(spans[-1].center, source.center)
        for previous, following in zip(spans, spans[1:]):
            self.assertEqual(previous.center, following.motion.start)
        self.assertAlmostEqual(sum(span.density_rate * .025 for span in spans), .3)
        self.assertTrue(all(span.motion.velocity == (2, 0, 0) for span in spans))
        with self.assertRaises(ValueError): source_span(source, .8, .2)
