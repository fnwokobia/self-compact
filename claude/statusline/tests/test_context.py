"""Payload-first resolution.

The fixture is a real statusLine payload captured from Claude Code 2.1.296.
Every assumption made about the payload before that capture was wrong, so the
shape is pinned here.
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from context import resolve, DEFAULT_WINDOW, env_float, env_int

REAL = {
    "session_id": "bbe17caf", "transcript_path": "/nonexistent/on/purpose.jsonl",
    "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
    "version": "2.1.296", "exceeds_200k_tokens": True,
    "cost": {"total_cost_usd": 91.50882674999997},
    "rate_limits": {"five_hour": {"used_percentage": 2}, "seven_day": {"used_percentage": 12}},
    "context_window": {
        "total_input_tokens": 349914, "total_output_tokens": 316,
        "context_window_size": 1000000, "used_percentage": 35,
        "current_usage": {"input_tokens": 2, "output_tokens": 316,
                          "cache_creation_input_tokens": 312,
                          "cache_read_input_tokens": 349600},
    },
}


class TestPayloadPath(unittest.TestCase):
    def test_uses_payload_not_transcript(self):
        """transcript_path here does not exist; resolution must still succeed."""
        c = resolve(REAL)
        self.assertEqual(c.source, "payload")
        self.assertIsNotNone(c.usage)

    def test_window_is_authoritative_not_guessed(self):
        self.assertEqual(resolve(REAL).window, 1_000_000)

    def test_totals_match_the_hosts_own_figure(self):
        c = resolve(REAL)
        self.assertEqual(c.usage.context_tokens, 349_914)

    def test_percentage_matches_host_used_percentage(self):
        c = resolve(REAL)
        self.assertEqual(round(c.usage.context_tokens / c.window * 100), 35)

    def test_cache_split_is_preserved(self):
        c = resolve(REAL)
        self.assertEqual(c.usage.cache_read, 349_600)
        self.assertEqual(c.usage.cache_creation, 312)
        self.assertAlmostEqual(c.usage.cache_hit_pct, 99.91, places=1)

    def test_window_override_wins(self):
        self.assertEqual(resolve(REAL, 250_000).window, 250_000)

    def test_total_input_tokens_reconciles_a_disagreement(self):
        """When the host's total exceeds the parts, trust the host."""
        p = {"context_window": {"total_input_tokens": 500_000, "context_window_size": 1_000_000,
                                "current_usage": {"input_tokens": 1, "cache_read_input_tokens": 100}}}
        self.assertEqual(resolve(p).usage.context_tokens, 500_000)


class TestFallbackPath(unittest.TestCase):
    def test_no_context_window_falls_back(self):
        c = resolve({"transcript_path": "/nope.jsonl", "model": "claude-opus-5"})
        self.assertEqual(c.source, "none")
        self.assertEqual(c.window, DEFAULT_WINDOW)

    def test_exceeds_200k_flag_lifts_the_guess(self):
        """The host telling us 200k cannot be right must raise the assumption.

        Written against the flag rather than against DEFAULT_WINDOW, so it stays
        meaningful however the default is set: with a 200k default the flag has to
        lift it, and with a 1M default the two simply must not contradict.
        """
        c = resolve({"transcript_path": "/nope.jsonl", "exceeds_200k_tokens": True})
        self.assertGreaterEqual(c.window, 1_000_000)

    def test_1m_model_id_lifts_the_guess(self):
        c = resolve({"transcript_path": "/nope.jsonl", "model": {"id": "claude-opus-5[1m]"}})
        self.assertEqual(c.window, 1_000_000)


if __name__ == "__main__":
    unittest.main()


class TestWindowSelfCorrection(unittest.TestCase):
    """A Stop payload has no context_window and no model id.

    Regression: on 2026-10-11 a real 1M session rendered as '159%  318.2k/200.0k'
    because the fallback assumed 200k. Observed usage is a hard lower bound on
    the window, so the guess must be promoted rather than left impossible.
    """

    def _transcript(self, ctx_tokens):
        import json, tempfile, os
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"usage": {
                "input_tokens": 0, "cache_read_input_tokens": ctx_tokens}}}) + "\n")
        return path

    def test_usage_above_the_default_raises_the_assumption(self):
        """Must exercise the correction, not pass because the default already fits.

        The earlier version fed 318,200 and asserted window == 1,000,000. Once
        DEFAULT_WINDOW became 1M that was true WITHOUT the correction running --
        a vacuous test guarding dead code. This feeds a figure above the default,
        so the branch has to fire for the assertion to hold.
        """
        import os
        over = DEFAULT_WINDOW + 400_000
        p = self._transcript(over)
        c = resolve({"transcript_path": p})
        self.assertGreater(c.window, DEFAULT_WINDOW)
        self.assertEqual(c.window, over)
        self.assertLessEqual(c.usage.context_tokens / c.window * 100, 100)
        os.unlink(p)

    def test_usage_below_the_window_keeps_the_default(self):
        """Observed usage below the window proves nothing, so the default stands."""
        import os
        p = self._transcript(50_000)
        self.assertEqual(resolve({"transcript_path": p}).window, DEFAULT_WINDOW)
        os.unlink(p)

    def test_beyond_every_tier_still_never_exceeds_100pct(self):
        import os
        p = self._transcript(1_400_000)
        c = resolve({"transcript_path": p})
        self.assertGreaterEqual(c.window, 1_400_000)
        os.unlink(p)

    def test_explicit_override_is_never_overridden(self):
        import os
        p = self._transcript(318_200)
        self.assertEqual(resolve({"transcript_path": p}, 200_000).window, 200_000)
        os.unlink(p)


class TestSharedEnvReaders(unittest.TestCase):
    """One reader for both surfaces: the defect class was divergent env handling."""

    def setUp(self):
        import os
        self._saved = {k: os.environ.get(k) for k in ("SELF_COMPACT_SOFT", "SELF_COMPACT_WINDOW")}

    def tearDown(self):
        import os
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_garbage_falls_back_rather_than_raising(self):
        import os
        os.environ["SELF_COMPACT_SOFT"] = "abc"
        self.assertEqual(env_float("SELF_COMPACT_SOFT", 60), 60)
        os.environ["SELF_COMPACT_SOFT"] = ""
        self.assertEqual(env_float("SELF_COMPACT_SOFT", 60), 60)

    def test_int_reader_returns_none_rather_than_raising(self):
        import os
        os.environ["SELF_COMPACT_WINDOW"] = "not-a-number"
        self.assertIsNone(env_int("SELF_COMPACT_WINDOW"))
        os.environ["SELF_COMPACT_WINDOW"] = "250000"
        self.assertEqual(env_int("SELF_COMPACT_WINDOW"), 250_000)

    def test_unset_is_not_an_error(self):
        import os
        os.environ.pop("SELF_COMPACT_WINDOW", None)
        self.assertIsNone(env_int("SELF_COMPACT_WINDOW"))
        self.assertEqual(env_float("SELF_COMPACT_SOFT", 60), 60)
