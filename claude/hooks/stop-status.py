#!/usr/bin/env python3
"""Stop hook: surface the context gauge where the status line cannot reach.

The statusLine is a TUI construct (`StatusLineCommand`) and renders only in the
terminal -- verified 2026-10-11, it does not even run under `claude -p`. Claude
on the web and in the desktop app render the *transcript* instead.

A Stop hook's `systemMessage` does reach the transcript. Verified on the same
date, one hook firing wrote three entries:

    attachment / hook_success         -- raw stdout
    attachment / hook_system_message  -- content: the message itself
    system     / stop_hook_summary    -- level: "suggestion"

So this hook prints the same gauge once per assistant turn, and it shows up on
every client, not just the terminal.

Note the Stop payload does NOT carry `context_window` -- it has session_id,
transcript_path, cwd, prompt_id, permission_mode, effort, hook_event_name,
stop_hook_active, last_assistant_message, background_tasks, session_crons. So
unlike the statusLine this must fall back to reading the transcript, which is
why the transcript reader is still in the tree.

    "hooks": { "Stop": [ { "matcher": "",
      "hooks": [ { "type": "command", "command": ".../stop-status.py" } ] } ] }

ONE-TURN LAG (measured 2026-10-11). The Stop hook runs before the current
turn's usage is flushed to the transcript, so it reports the PREVIOUS turn's
figures and emits nothing at all on the first turn of a session. A three-turn
probe produced three `stop_hook_summary` markers but two gauges.

CONFIRMED NOT A FLUSH RACE (0-diagrams, 2026-10-11). The hook fired at 12:09:00,
three seconds after the turn's usage carried timestamp 12:08:57, and still read
the previous turn. The timestamp is when the turn STARTED; the line is appended
only after Stop hooks run. So polling cannot close this -- the data does not
exist yet when the hook executes. Left as-is, and the output is labelled
"(prev turn)" instead, because the cache share in particular can swing from
10.2% to 99.9% between consecutive turns.

Set SELF_COMPACT_STOP_QUIET=1 to disable without unwiring it.
"""

from __future__ import annotations
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "statusline"))
from bar import render        # noqa: E402
from context import resolve, env_float, env_int   # noqa: E402

ANSI = re.compile(r"\033\[[0-9;]*m")


def build(payload: dict) -> str | None:
    if os.environ.get("SELF_COMPACT_STOP_QUIET") == "1":
        return None
    # Shared readers, so a stray value degrades the same way on both surfaces.
    # These used to be bare float(os.environ.get(...)): SELF_COMPACT_SOFT=abc made
    # this hook raise, main() print {}, and the gauge vanish from web and the app
    # while the terminal kept rendering -- the same two-surfaces-disagree defect
    # this file was changed to fix.
    soft = env_float("SELF_COMPACT_SOFT", 60)
    warn = env_float("SELF_COMPACT_WARN", 75)
    forced = env_float("SELF_COMPACT_FORCED", 85)

    ctx = resolve(payload, env_int("SELF_COMPACT_WINDOW"))
    if ctx.usage is None:
        return None

    used = ctx.usage.context_tokens
    window = ctx.window or 1
    pct = used / window * 100
    gauge = render(pct, ctx.usage.cache_read / window * 100, soft, warn, forced)

    def human(n: int) -> str:
        return f"{n/1_000_000:.2f}M" if n >= 1_000_000 else f"{n/1_000:.1f}k" if n >= 1_000 else str(n)

    if pct > 100:
        # Say the window is wrong rather than pegging at 100%. The status line has
        # always done this; without it here, an override that is too small printed a
        # bare "450%" on one surface and a diagnosis on the other.
        return (f"{gauge.text}  window looks wrong: {human(used)} used vs "
                f"{human(window)} assumed -- set SELF_COMPACT_WINDOW")

    cache = "100%" if ctx.usage.cache_hit_pct >= 99.995 else f"{ctx.usage.cache_hit_pct:.1f}%"
    # "prev turn" is not decoration. Measured on 0-diagrams 2026-10-11: the hook
    # reported cache 10.2% while the live value was 99.9%, because the figures
    # are a full turn old. Context size barely drifts, but the cache share can
    # swing an order of magnitude between consecutive turns, so an unlabelled
    # number here reads as current and is not.
    suffix = "" if ctx.source == "payload" else "  (prev turn)"
    # No ANSI: this is rendered by web and the app, not only a terminal.
    return ANSI.sub("", f"{gauge.text}  {human(used)}/{human(window)}  cache {cache}{suffix}")


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    try:
        msg = build(payload)
    except Exception:
        msg = None
    # Silence is a valid hook result; never block the turn on a cosmetic gauge.
    print(json.dumps({"systemMessage": msg}) if msg else "{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
