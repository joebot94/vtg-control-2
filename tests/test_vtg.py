"""Offline tests: timing math, presets round-trip, protocol parsers, worker
ordering against the mock. Run: python -m unittest discover tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtg import presets, protocol  # noqa: E402
from vtg.capture import CaptureLog, load_jsonl, save_jsonl  # noqa: E402
from vtg.session import open_session  # noqa: E402
from vtg.timing import ClockSource, Timing, TimingError, example_320x240  # noqa: E402


class TimingMath(unittest.TestCase):
    def test_example_totals_and_clocks(self):
        t = example_320x240()
        self.assertEqual(t.h_total, 416)
        self.assertEqual(t.v_total, 262)
        self.assertAlmostEqual(t.pixel_clock, 416 * 262 * 59.94, places=3)  # 6.533 MHz
        self.assertAlmostEqual(t.h_freq, 262 * 59.94, places=6)             # 15.704 kHz
        self.assertAlmostEqual(t.refresh, 59.94, places=9)

    def test_brief_mockup_numbers_were_inconsistent(self):
        # 416 x 256 @ 59.94 is 6.383 MHz / 15.345 kHz, not 6.294 / 15.734.
        t = Timing(width=320, height=240, h_front_porch=16, h_sync_width=32, h_back_porch=48,
                   v_front_porch=3, v_sync_width=3, v_back_porch=10, clock_value=59.94)
        self.assertAlmostEqual(t.pixel_clock / 1e6, 6.383, places=3)
        self.assertAlmostEqual(t.h_freq / 1e3, 15.345, places=3)

    def test_h_freq_authoritative(self):
        t = example_320x240().with_clock_source(ClockSource.H_FREQ)
        t.clock_value = 15734.264
        self.assertAlmostEqual(t.h_freq, 15734.264, places=6)
        self.assertAlmostEqual(t.pixel_clock, 15734.264 * 416, places=3)
        self.assertAlmostEqual(t.refresh, 15734.264 / 262, places=6)

    def test_pixel_clock_authoritative(self):
        t = example_320x240().with_clock_source(ClockSource.PIXEL_CLOCK)
        t.clock_value = 6_500_000
        self.assertEqual(t.pixel_clock, 6_500_000)
        self.assertAlmostEqual(t.h_freq, 6_500_000 / 416)

    def test_switching_source_preserves_timing(self):
        a = example_320x240()
        for src in ClockSource:
            b = a.with_clock_source(src)
            self.assertAlmostEqual(b.pixel_clock, a.pixel_clock, places=3)
            self.assertAlmostEqual(b.refresh, a.refresh, places=9)

    def test_validation(self):
        with self.assertRaises(TimingError):
            Timing(width=0).validate()
        with self.assertRaises(TimingError):
            Timing(h_sync_width=0).validate()
        with self.assertRaises(TimingError):
            Timing(h_sync_polarity="x").validate()
        with self.assertRaises(TimingError):
            Timing(clock_value=0).validate()

    def test_interlaced_warns(self):
        self.assertTrue(Timing(interlaced=True).warnings())
        self.assertFalse(Timing().warnings())


class Presets(unittest.TestCase):
    def test_round_trip_each_source(self):
        with tempfile.TemporaryDirectory() as d:
            for src in ClockSource:
                t = example_320x240().with_clock_source(src)
                p = presets.save(t, Path(d) / f"{src.value}.json")
                back = presets.load(p)
                self.assertEqual(back.clock_source, src)
                self.assertEqual(back.to_dict(), t.to_dict())

    def test_briefs_plain_format_loads(self):
        d = {"name": "320x240 CRT", "width": 320, "height": 240, "refresh": 59.94,
             "h_front_porch": 16, "h_sync_width": 32, "h_back_porch": 48,
             "v_front_porch": 3, "v_sync_width": 3, "v_back_porch": 10,
             "h_sync_polarity": "-", "v_sync_polarity": "-", "interlaced": False}
        t = presets.timing_from_dict(d)
        self.assertEqual(t.clock_source, ClockSource.REFRESH)
        self.assertEqual(t.v_total, 256)


class Parsers(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(protocol.parse_model("60-564-02"), "VTG 400D")
        self.assertEqual(protocol.parse_int("Ire050"), 50)
        self.assertEqual(protocol.parse_resolution("001*99"), "240p")
        self.assertEqual(protocol.parse_resolution("Rte 010*06"), "1080i")
        self.assertIsNone(protocol.parse_resolution("099*99"))
        self.assertAlmostEqual(protocol.parse_temperature_f("Tmp +095.5F"), 95.5)
        self.assertEqual(protocol.parse_pattern("9"), "PLUGE")

    def test_program_timing_is_stubbed(self):
        log = CaptureLog()
        s = open_session("MOCK", 9600, log)
        try:
            with self.assertRaises(protocol.NotCaptured):
                s.vtg.program_timing(example_320x240())
            self.assertFalse(s.vtg.supports_custom_timing)
        finally:
            s.close()


class WorkerOrdering(unittest.TestCase):
    def test_interleaved_queries_get_their_own_replies(self):
        log = CaptureLog()
        s = open_session("MOCK", 9600, log)
        try:
            s.vtg.set_ire(40).result(2)
            s.vtg.set_pattern("PLUGE").result(2)
            futs = []
            for _ in range(10):
                futs += [s.vtg.query_ire(), s.vtg.query_pattern(),
                         s.vtg.query_resolution(), s.vtg.query_temperature()]
            got = [f.result(5) for f in futs]
            self.assertEqual(got[0::4], [40] * 10)
            self.assertEqual(got[1::4], ["PLUGE"] * 10)
            self.assertEqual(got[2::4], ["240p"] * 10)
            self.assertTrue(all(isinstance(x, float) for x in got[3::4]))
        finally:
            s.close()

    def test_capture_jsonl_round_trip(self):
        log = CaptureLog()
        log.tx(b"001*99=")
        log.rx(b"\x1b\x00ok\r\n")
        log.info("hello")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.jsonl"
            save_jsonl(log.events(), p)
            back = load_jsonl(p)
        self.assertEqual(back, log.events())


if __name__ == "__main__":
    unittest.main()
