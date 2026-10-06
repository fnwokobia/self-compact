import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/self-compact/scripts"
sys.path.insert(0, str(SCRIPTS))
import self_compact as plugin
spec = importlib.util.spec_from_file_location("plugin_setup", SCRIPTS / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"SELF_COMPACT_DATA": str(self.root / "data"), "SELF_COMPACT_CONFIG": str(self.root / "config.json")})
        self.env.start()
        (self.root / "config.json").write_text('{"context_window":100000}')
        self.path = self.root / "transcript.jsonl"
        self.usage(55000)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def usage(self, used):
        self.path.write_text(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"total_tokens": used}, "total_token_usage": {"total_tokens": 99999999},
            "model_context_window": 100000}}}) + "\n" + json.dumps({"type": "event_msg", "payload": {
                "type": "user_message", "message": "Finish task A. Next action: verify A."}}) + "\n")

    def call(self, event, **extra):
        return plugin.handle({"hook_event_name": event, "session_id": "session-A", "turn_id": "turn-A",
                              "transcript_path": str(self.path), "cwd": str(self.root), **extra})

    def test_current_not_cumulative_usage(self):
        self.usage(100)
        self.assertEqual(self.call("PostToolUse"), {})

    def test_one_warning(self):
        self.assertIn("55.0%", self.call("PostToolUse")["systemMessage"])
        self.assertEqual(self.call("PostToolUse"), {})

    def test_agent_note_saved_and_task_continues(self):
        self.assertEqual(self.call("Stop")["decision"], "block")
        note = "Goal: finish A.\nNext: verify A. Unicode: ✓"
        result = self.call("Stop", last_assistant_message=plugin.START + note + plugin.END, stop_hook_active=True)
        self.assertEqual(result["decision"], "block")
        s = plugin.Session("session-A")
        with s.locked():
            self.assertEqual(s.note(), note)
        self.assertNotIn("decision", self.call("Stop", last_assistant_message="Done", stop_hook_active=True))

    def test_checkpoint_before_compaction_and_exact_restore(self):
        self.call("PreCompact", trigger="auto")
        s = plugin.Session("session-A")
        with s.locked():
            saved = s.note()
        self.call("PostCompact", trigger="auto")
        result = self.call("SessionStart", source="compact")
        self.assertIn(saved, result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.call("PostToolUse"), {})
        self.usage(56000)
        self.assertIn("warning", self.call("PostToolUse")["systemMessage"])

    def test_duplicate_compact_callback_does_not_advance_cycle(self):
        self.call("PreCompact", trigger="auto")
        self.call("PostCompact", trigger="auto")
        self.call("SessionStart", source="compact")
        self.assertEqual(self.call("SessionStart", source="compact"), {})
        with plugin.Session("session-A").locked() as s:
            self.assertEqual(s.state["cycle"], 1)

    def test_no_shrink_stops_repeated_auto_compaction(self):
        self.usage(70000)
        self.call("PreCompact", trigger="auto")
        self.call("PostCompact", trigger="auto")
        self.call("SessionStart", source="compact")
        self.usage(71000)
        self.call("PostToolUse")
        self.assertFalse(self.call("PreCompact", trigger="auto")["continue"])
        self.assertNotIn("continue", self.call("PreCompact", trigger="manual"))

    def test_agent_note_whitespace_preserved(self):
        self.call("Stop")
        note = "\n  Goal A.\nNext B.\n"
        self.call("Stop", last_assistant_message=plugin.START + note + plugin.END)
        with plugin.Session("session-A").locked() as s:
            self.assertEqual(s.note(), note)

    def test_missing_checkpoint_blocks_native_compaction(self):
        self.path.unlink()
        self.assertFalse(self.call("PreCompact")["continue"])

    def test_corrupt_note_refused(self):
        self.call("PreCompact")
        s = plugin.Session("session-A")
        with s.locked():
            (s.folder / s.state["note"]["file"]).write_text("changed")
            with self.assertRaises(ValueError):
                s.note()

    def test_sessions_isolated_and_path_traversal_safe(self):
        self.assertNotEqual(plugin.Session("../session-A").folder, plugin.Session("session-A").folder)
        self.assertEqual(plugin.Session("../session-A").folder.parent, plugin.data_root() / "sessions")

    def test_validation(self):
        (self.root / "config.json").write_text('{"notice":"70%","warning":"55%"}')
        with self.assertRaises(ValueError):
            plugin.settings()

    def test_partial_line_ignored(self):
        with self.path.open("a") as f:
            f.write('{"unfinished')
        self.assertEqual(plugin.transcript(self.path)[1], (55000, 100000))

    def test_setup_preserves_other_settings_and_idempotent(self):
        source = 'model = "keep-me"\nmodel_auto_compact_token_limit = 123\n[features]\nhooks = true\n[profiles.special]\nmodel_auto_compact_token_limit = 456\n'
        result = setup.update_native(source, 65000)
        self.assertIn('model = "keep-me"', result)
        self.assertIn("model_auto_compact_token_limit = 456", result)
        self.assertNotIn("= 123", result)
        self.assertEqual(result, setup.update_native(result, 65000))


if __name__ == "__main__":
    unittest.main()
