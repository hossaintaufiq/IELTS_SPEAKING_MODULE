import unittest

from usage_meter import UsageMeter


def done(response_id, audio_in, cached, audio_out):
    return {
        "type": "response.done",
        "event_id": f"evt_{response_id}",
        "response": {
            "id": response_id,
            "usage": {
                "input_token_details": {
                    "audio_tokens": audio_in,
                    "text_tokens": 50,
                    "cached_tokens": cached,
                    "cached_tokens_details": {"audio_tokens": cached},
                },
                "output_token_details": {"audio_tokens": audio_out, "text_tokens": 10},
            },
        },
    }


class UsageMeterTests(unittest.TestCase):
    def test_splits_cached_and_uncached_audio(self):
        meter = UsageMeter("realtime-2.1")
        meter.feed(done("r1", audio_in=1000, cached=400, audio_out=200))
        self.assertEqual((meter.audio_in, meter.audio_cached, meter.audio_out), (600, 400, 200))

    def test_cost_matches_hand_calculation(self):
        meter = UsageMeter("realtime-2.1")
        meter.feed(done("r1", audio_in=1000, cached=400, audio_out=200))
        expected = (600 * 32 + 400 * 0.40 + 200 * 64) / 1e6
        self.assertAlmostEqual(meter.audio_cost_usd(), expected)

    def test_duplicate_events_are_counted_once(self):
        meter = UsageMeter("realtime-2.1-mini")
        event = done("r1", 500, 0, 100)
        self.assertTrue(meter.feed(event))
        self.assertFalse(meter.feed(event))
        self.assertEqual(meter.responses, 1)

    def test_ignores_other_events_and_missing_usage(self):
        meter = UsageMeter("realtime-2.1")
        self.assertFalse(meter.feed({"type": "response.created"}))
        self.assertFalse(meter.feed({"type": "response.done", "response": {"id": "x"}}))
        self.assertEqual(meter.responses, 0)

    def test_accumulates_across_responses_and_reports_cache_hit_rate(self):
        meter = UsageMeter("realtime-2.1")
        meter.feed(done("r1", 1000, 0, 100))
        meter.feed(done("r2", 2000, 1500, 100))
        summary = meter.summary()
        self.assertEqual(summary["responses"], 2)
        self.assertEqual(summary["audio_cached_tokens"], 1500)
        self.assertEqual(summary["cache_hit_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
