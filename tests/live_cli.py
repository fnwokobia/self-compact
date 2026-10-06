#!/usr/bin/env python3
"""Opt-in real CLI hook test. Uses existing login, isolated hooks and scratch work."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import argparse
import random

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/self-compact"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto-compact", action="store_true", help="Also exercise native automatic compaction with disposable calibration text")
    options = parser.parse_args()
    folder = Path(tempfile.mkdtemp(prefix="self-compact-CLI-test-"))
    config = json.loads((PLUGIN / "config.json").read_text())
    # Tiny notification thresholds exercise the hooks without filling the window.
    limit = 26000 if options.auto_compact else 167960
    config.update({"notice": 1, "warning": 2, "compact": limit})
    (folder / "config.json").write_text(json.dumps(config))
    args = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "--dangerously-bypass-hook-trust", "--json", "--model", "gpt-6-astra",
            "--sandbox", "read-only", "-C", str(folder), "-c", "features.apps=false",
            "-c", "model_auto_compact_token_limit=" + str(limit),
            "-c", 'model_auto_compact_token_limit_scope="total"']
    command = ("SELF_COMPACT_DATA=" + shlex.quote(str(folder / "data")) +
               " SELF_COMPACT_CONFIG=" + shlex.quote(str(folder / "config.json")) +
               " python3 " + shlex.quote(str(PLUGIN / "scripts/self_compact.py")) + " hook")
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
    for event in hooks:
        # Command-line hook definitions apply only to this test invocation.
        value = "[{hooks=[{type=\"command\",command=" + json.dumps(command) + ",timeout=10}]}]"
        args.extend(["-c", "hooks." + event + "=" + value])
    prompt = "This is an integration test. Do not use any tools or access any files. Reply exactly CLI_PLUGIN_OK. If a self-compact hook requests an internal note, follow it, then return to this original request."
    if options.auto_compact:
        rng = random.Random(42)
        filler = " ".join(str(rng.randrange(100000, 999999)) for _ in range(6000))
        prompt += "\nThe following calibration data is meaningless and may be discarded during compaction:\n" + filler
        prompt += "\nEND calibration data. The only task is to reply exactly CLI_PLUGIN_OK. Do not use tools or access files."
    base_args = list(args)
    args.append(prompt)
    print("Scratch evidence:", folder, flush=True)
    with (folder / "cli.jsonl").open("w") as out, (folder / "cli.stderr").open("w") as err:
        result = subprocess.run(args, stdout=out, stderr=err, timeout=180)
    if options.auto_compact and result.returncode == 0:
        initial = [json.loads(line) for line in (folder / "cli.jsonl").read_text().splitlines()]
        thread_id = next(m["thread_id"] for m in initial if m.get("type") == "thread.started")
        # Native pre-turn compaction uses the measured usage of the previous turn.
        # A Stop continuation does not always re-enter that pre-turn path.
        with (folder / "cli-resume.jsonl").open("w") as out, (folder / "cli.stderr").open("a") as err:
            result = subprocess.run(base_args + ["resume", thread_id,
                "Continue the integration test: reply exactly CLI_PLUGIN_OK. Use no tools and access no files."],
                stdout=out, stderr=err, timeout=180)
    print("CLI exit:", result.returncode)
    for p in (folder / "data/sessions").glob("*/events.jsonl"):
        entries = [json.loads(line) for line in p.read_text().splitlines()]
        print(json.dumps({"events": entries}, indent=2))
    if result.returncode:
        print((folder / "cli.stderr").read_text()[-4000:])
        print((folder / "cli.jsonl").read_text()[-4000:])
        raise SystemExit(result.returncode)
    transcript_file = folder / ("cli-resume.jsonl" if options.auto_compact else "cli.jsonl")
    print(transcript_file.read_text()[-3000:])
    entries = [json.loads(line) for p in (folder / "data/sessions").glob("*/events.jsonl") for line in p.read_text().splitlines()]
    events = [e["event"] for e in entries]
    if "note_saved" not in events:
        raise SystemExit("FAIL: no agent/checkpoint note was saved")
    if options.auto_compact and ("compaction_allowed" not in events or "note_restored" not in events):
        raise SystemExit("FAIL: automatic compaction lifecycle was not observed")
    messages = [json.loads(line) for line in transcript_file.read_text().splitlines()]
    replies = [m["item"].get("text") for m in messages if m.get("item", {}).get("type") == "agent_message"]
    if not replies or replies[-1] != "CLI_PLUGIN_OK":
        raise SystemExit("FAIL: final continuation marker missing")
    print("PASS: live CLI lifecycle and final continuation verified")


if __name__ == "__main__":
    main()
