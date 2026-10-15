"""Entry-point tests. The contract that matters: it must never raise."""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "statusline.py")
sys.path.insert(0, os.path.join(HERE, ".."))
from transcript import read_latest_usage, Usage  # noqa: E402


def run(stdin: str, env=None):
    e = dict(os.environ)
    e.pop("SELF_COMPACT_DEBUG", None)
    e.update(env or {})
    p = subprocess.run([sys.executable, SCRIPT], input=stdin, capture_output=True, text=True, env=e)
    return p


def transcript(*usages) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for u in usages:
            fh.write(json.dumps({"type": "assistant", "message": {"usage": u}}) + "\n")
    return path


class TestNeverCrashes(unittest.TestCase):
    """Every one of these used to be a way to take the status bar down."""

    def test_empty_stdin(self):
        p = run("")
        self.assertEqual(p.returncode, 0)
        self.assertTrue(p.stdout.strip())

    def test_malformed_json(self):
        self.assertEqual(run("}{ not json").returncode, 0)

    def test_missing_transcript(self):
        self.assertEqual(run('{"transcript_path":"/nope/x.jsonl"}').returncode, 0)

    def test_transcript_with_garbage_lines(self):
        path = transcript({"input_tokens": 1, "cache_read_input_tokens": 10})
        with open(path, "a") as fh:
            fh.write("not json at all\n{}\n")
        p = run(json.dumps({"transcript_path": path}))
        self.assertEqual(p.returncode, 0)
        os.unlink(path)

    def test_model_as_bare_string(self):
        self.assertEqual(run('{"model":"claude-opus-5"}').returncode, 0)


class TestRealPayload(unittest.TestCase):
    """End-to-end against a real statusLine payload captured from Claude Code 2.1.296."""

    REAL = json.dumps({
        "transcript_path": "/nonexistent.jsonl",
        "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
        "exceeds_200k_tokens": True,
        "cost": {"total_cost_usd": 91.50882674999997},
        "rate_limits": {"five_hour": {"used_percentage": 2},
                        "seven_day": {"used_percentage": 12}},
        "context_window": {"total_input_tokens": 349914, "context_window_size": 1000000,
                           "used_percentage": 35,
                           "current_usage": {"input_tokens": 2, "output_tokens": 316,
                                             "cache_creation_input_tokens": 312,
                                             "cache_read_input_tokens": 349600}},
    })

    def test_renders_the_hosts_own_percentage(self):
        self.assertIn("35%", run(self.REAL).stdout)

    def test_no_window_warning_on_a_correct_payload(self):
        self.assertNotIn("window looks wrong", run(self.REAL).stdout)

    def test_shows_cache_and_cost_and_limits(self):
        out = run(self.REAL).stdout
        self.assertIn("cache 99.9%", out)
        self.assertIn("1.51", out)
        self.assertIn("5h 2%", out)
        self.assertIn("7d 12%", out)

    def test_rate_limits_can_be_suppressed(self):
        self.assertNotIn("5h", run(self.REAL, {"SELF_COMPACT_RATELIMITS": "0"}).stdout)


class TestRendering(unittest.TestCase):
    def test_reads_last_turn_not_first(self):
        path = transcript(
            {"input_tokens": 1, "cache_read_input_tokens": 10},
            {"input_tokens": 2, "cache_read_input_tokens": 90_000, "cache_creation_input_tokens": 1_000},
        )
        u = read_latest_usage(path)
        self.assertEqual(u.context_tokens, 91_002)
        os.unlink(path)

    def test_sidechain_turns_are_ignored(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5}}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "isSidechain": True,
                                 "message": {"usage": {"input_tokens": 999_999}}}) + "\n")
        self.assertEqual(read_latest_usage(path).context_tokens, 5)
        os.unlink(path)

    def test_window_env_override_changes_percent(self):
        path = transcript({"cache_read_input_tokens": 100_000})
        a = run(json.dumps({"transcript_path": path}), {"SELF_COMPACT_WINDOW": "200000"}).stdout
        b = run(json.dumps({"transcript_path": path}), {"SELF_COMPACT_WINDOW": "1000000"}).stdout
        self.assertIn("50%", a)
        self.assertIn("10%", b)
        os.unlink(path)

    def test_cache_hit_is_not_rounded_up_to_100(self):
        path = transcript({"input_tokens": 400, "cache_read_input_tokens": 99_600})
        out = run(json.dumps({"transcript_path": path})).stdout
        self.assertIn("99.6%", out)
        self.assertNotIn("cache 100%", out)
        os.unlink(path)

    def test_no_usage_yet_still_renders_thresholds(self):
        self.assertIn("waiting for first turn", run("{}").stdout)

    def test_single_line_output(self):
        path = transcript({"cache_read_input_tokens": 50_000})
        self.assertEqual(len(run(json.dumps({"transcript_path": path})).stdout.strip().splitlines()), 1)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()


class TestHostPrefix(unittest.TestCase):
    """A destination may already own its status line; the gauge must be additive.

    A machine may already print its own banner; adopting the gauge must not
    cost you something you already had.
    """

    def _t(self):
        return transcript({"input_tokens": 10, "cache_read_input_tokens": 50_000})

    def test_prefix_is_emitted(self):
        p = self._t()
        out = run(json.dumps({"transcript_path": p}), {"SELF_COMPACT_PREFIX": "web01 "}).stdout
        self.assertTrue(out.startswith("web01 "), out[:40])
        os.unlink(p)

    def test_prefix_present_on_the_waiting_path_too(self):
        out = run("{}", {"SELF_COMPACT_PREFIX": "web01 "}).stdout
        self.assertTrue(out.startswith("web01 "))

    def test_absent_prefix_changes_nothing(self):
        p = self._t()
        a = run(json.dumps({"transcript_path": p})).stdout
        self.assertFalse(a.startswith("web01"))
        os.unlink(p)
