"""Stop-hook tests. Fixture is the real Stop payload captured 2026-10-11."""
import json, os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from context import DEFAULT_WINDOW  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "hooks", "stop-status.py")


def temp_transcript(*usages):
    """Fixtures go to a temp dir, never beside the tests.

    Found on EC2 2026-10-11: the package was installed to /opt and run by a
    second account, and three tests failed with PermissionError because they
    wrote their fixtures into the tests directory. The validation gate has to
    work from a read-only or shared install, or it is not a gate.
    """
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for u in usages:
            fh.write(json.dumps({"type": "assistant", "message": {"usage": u}}) + "\n")
    return path

REAL_STOP = {
    "session_id": "34d5a459", "transcript_path": "/nonexistent.jsonl",
    "cwd": "/tmp", "prompt_id": "ae16ef29", "permission_mode": "bypassPermissions",
    "effort": {"level": "medium"}, "hook_event_name": "Stop",
    "stop_hook_active": False, "last_assistant_message": "ok",
    "background_tasks": [], "session_crons": [],
}


def run(payload, env=None):
    e = dict(os.environ); e.update(env or {})
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, env=e)


class TestStopHook(unittest.TestCase):
    def test_always_emits_valid_json(self):
        for p in ({}, REAL_STOP, {"transcript_path": "/nope"}):
            r = run(p)
            self.assertEqual(r.returncode, 0)
            json.loads(r.stdout)  # must parse or the hook is broken

    def test_silent_when_no_usage_available(self):
        """A cosmetic gauge must never block a turn."""
        self.assertEqual(json.loads(run(REAL_STOP).stdout), {})

    def test_quiet_switch(self):
        self.assertEqual(json.loads(run(REAL_STOP, {"SELF_COMPACT_STOP_QUIET": "1"}).stdout), {})

    def test_no_ansi_in_output(self):
        """Web and the app render this; escape codes would show as literals."""
        p = dict(REAL_STOP)
        p["transcript_path"] = temp_transcript(
            {"input_tokens": 10, "cache_read_input_tokens": 90_000})
        out = json.loads(run(p).stdout)
        self.assertIn("systemMessage", out)
        self.assertNotIn("\033", out["systemMessage"])
        os.unlink(p["transcript_path"])

    def test_malformed_stdin(self):
        r = subprocess.run([sys.executable, HOOK], input="}{", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        json.loads(r.stdout)


if __name__ == "__main__":
    unittest.main()


class TestKnownLimitations(unittest.TestCase):
    """Behaviour we have decided to live with, pinned so it cannot regress silently."""

    def test_silent_when_transcript_has_no_usage_yet(self):
        """First turn of a session: the hook runs before usage is flushed.

        Measured 2026-10-11 -- three turns produced three stop_hook_summary
        markers but only two gauges. Silence is correct here, not a failure.
        """
        p = dict(REAL_STOP)
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        p["transcript_path"] = path
        self.assertEqual(json.loads(run(p).stdout), {})
        os.unlink(p["transcript_path"])


class TestStalenessIsLabelled(unittest.TestCase):
    """Transcript-sourced figures are a full turn old and must say so.

    Measured on 0-diagrams 2026-10-11: the hook reported `cache 10.2%` while the
    live value was 99.9%, three seconds after the newer usage was timestamped.
    """

    def test_transcript_sourced_output_is_marked_prev_turn(self):
        p = dict(REAL_STOP)
        p["transcript_path"] = temp_transcript(
            {"input_tokens": 10, "cache_read_input_tokens": 90_000})
        msg = json.loads(run(p).stdout)["systemMessage"]
        self.assertIn("(prev turn)", msg)
        os.unlink(p["transcript_path"])

    def test_payload_sourced_output_is_not_marked(self):
        """If a payload ever carries context_window, the figures are live."""
        p = dict(REAL_STOP)
        p["context_window"] = {"context_window_size": 1_000_000,
                               "total_input_tokens": 100_000,
                               "current_usage": {"input_tokens": 5,
                                                 "cache_read_input_tokens": 99_995}}
        msg = json.loads(run(p).stdout)["systemMessage"]
        self.assertNotIn("(prev turn)", msg)


class TestWindowOverrideReachesTheHook(unittest.TestCase):
    """Regression: the hook ignored SELF_COMPACT_WINDOW, and the default was wrong.

    Found in a long-running 1M-window session. The status line read the override;
    this hook did not. On a 1M-window host that only mattered when usage was
    UNDER 200k -- above it the window self-correction supplied the right answer,
    which is how the bug reached production. At 89.5k the gauge reported "45%"
    (of a 200k default) where the truth was "9%" of 1M: a 5x overstatement of
    context pressure, on every Stop-hook render for that workspace.
    """

    def _p(self):
        p = dict(REAL_STOP)
        p["transcript_path"] = temp_transcript(
            {"input_tokens": 500, "cache_read_input_tokens": 89_000})
        return p

    def test_override_is_applied(self):
        """An explicit window must win over whatever the default happens to be."""
        p = self._p()
        msg = json.loads(run(p, {"SELF_COMPACT_WINDOW": "1000000"}).stdout)["systemMessage"]
        self.assertIn("1.00M", msg)
        self.assertIn(" 9%", msg)          # 89.5k of 1M
        os.unlink(p["transcript_path"])

    def test_a_200k_host_can_still_be_configured(self):
        """The override must work in both directions, not just upward."""
        p = self._p()
        msg = json.loads(run(p, {"SELF_COMPACT_WINDOW": "200000"}).stdout)["systemMessage"]
        self.assertIn("200.0k", msg)
        self.assertIn("45%", msg)
        os.unlink(p["transcript_path"])

    def test_hook_reports_a_wrong_window_instead_of_pegging_at_100(self):
        """The status line always diagnosed this; the hook used to print a bare 450%."""
        p = dict(REAL_STOP)
        p["transcript_path"] = temp_transcript({"cache_read_input_tokens": 900_000})
        msg = json.loads(run(p, {"SELF_COMPACT_WINDOW": "200000"}).stdout)["systemMessage"]
        self.assertIn("window looks wrong", msg)
        self.assertIn("SELF_COMPACT_WINDOW", msg)
        os.unlink(p["transcript_path"])

    def test_garbage_threshold_does_not_silence_the_hook(self):
        """SELF_COMPACT_SOFT=abc used to make this hook emit {} while the status
        line rendered normally -- the gauge vanished from web and the app only."""
        p = dict(REAL_STOP)
        p["transcript_path"] = temp_transcript({"cache_read_input_tokens": 300_000})
        out = json.loads(run(p, {"SELF_COMPACT_SOFT": "abc"}).stdout)
        self.assertIn("systemMessage", out)
        # The point is that it SPEAKS, not what percentage it reports -- that depends
        # on DEFAULT_WINDOW, which differs between deployments of this gauge.
        self.assertRegex(out["systemMessage"], r"\d+%")
        os.unlink(p["transcript_path"])

    def test_statusline_and_hook_agree_on_the_same_transcript(self):
        """The check that would have caught this: two surfaces, one answer."""
        import subprocess
        p = self._p()
        sl = os.path.join(HERE, "..", "statusline.py")
        a = subprocess.run([sys.executable, sl], input=json.dumps(p),
                           capture_output=True, text=True, env=dict(os.environ)).stdout
        b = json.loads(run(p).stdout)["systemMessage"]
        # Assert they AGREE, derived from the default, rather than hardcoding a window.
        expect = "89.5k/1.00M" if DEFAULT_WINDOW >= 1_000_000 else f"89.5k/{DEFAULT_WINDOW/1000:.1f}k"
        self.assertIn(expect, a)
        self.assertIn(expect, b)
        os.unlink(p["transcript_path"])
