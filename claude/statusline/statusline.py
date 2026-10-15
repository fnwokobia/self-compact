#!/usr/bin/env python3
"""Claude Code statusLine: a context gauge that shows the KV cache.

    "statusLine": { "type": "command", "command": "/path/to/statusline.py" }

Renders disler/self-compact-pi-agent's 20-cell context bar (MIT) against Claude
Code's own figures. `#` marks cells inside the KV-cached share, `=` used beyond
it, `-` free; `~` `!` `|` are the notice / warning / forced threshold markers.

Thresholds are percent of window. disler ships 10/20/30, tuned for out-loop
agents that must compact long before the wall; an interactive Claude Code
session auto-compacts near the top anyway, so the defaults here sit higher:

    SELF_COMPACT_SOFT=60 SELF_COMPACT_WARN=75 SELF_COMPACT_FORCED=85
    SELF_COMPACT_WINDOW=1000000     override the window (rarely needed now)
    SELF_COMPACT_RATELIMITS=0       hide the 5h/7d quota figures
    SELF_COMPACT_PREFIX="web01 "     text to print before the gauge
    SELF_COMPACT_DEBUG=/tmp/p.json  capture the raw payload

Never raises. A statusLine that throws takes the status bar down with it, so
every failure degrades to a plainer line.
"""

from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bar import render      # noqa: E402
from context import resolve, env_float, env_int  # noqa: E402

DEFAULTS = {"soft": 60.0, "warn": 75.0, "forced": 85.0}
DIM, RESET = "\033[2m", "\033[0m"
GREEN, YELLOW, RED = "\033[32m", "\033[33m", "\033[31m"






def _human(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _cache_pct(pct: float) -> str:
    """One decimal below 100, so a 99.6% hit never reads as a perfect 100%."""
    return "100%" if pct >= 99.995 else f"{pct:.1f}%"


def _model_label(payload: dict) -> str:
    model = payload.get("model")
    if isinstance(model, dict):
        return str(model.get("display_name") or model.get("id") or "claude")
    return str(model or "claude")


def _rate_limits(payload: dict) -> str | None:
    if os.environ.get("SELF_COMPACT_RATELIMITS") == "0":
        return None
    rl = payload.get("rate_limits")
    if not isinstance(rl, dict):
        return None
    bits = []
    for key, short in (("five_hour", "5h"), ("seven_day", "7d")):
        win = rl.get(key)
        if isinstance(win, dict) and isinstance(win.get("used_percentage"), (int, float)):
            bits.append(f"{short} {win['used_percentage']:.0f}%")
    return " ".join(bits) or None


def build_line(payload: dict) -> str:
    soft = env_float("SELF_COMPACT_SOFT", DEFAULTS["soft"])
    warn = env_float("SELF_COMPACT_WARN", DEFAULTS["warn"])
    forced = env_float("SELF_COMPACT_FORCED", DEFAULTS["forced"])

    label = _model_label(payload)
    ctx = resolve(payload, env_int("SELF_COMPACT_WINDOW"))

    if ctx.usage is None:
        gauge = render(None, 0, soft, warn, forced)
        pre = (os.environ.get("SELF_COMPACT_PREFIX") or "")
        return f"{pre}{DIM}{label}{RESET} {gauge.text} {DIM}· waiting for first turn{RESET}"

    used = ctx.usage.context_tokens
    window = ctx.window or 1
    used_pct = used / window * 100
    cached_pct = ctx.usage.cache_read / window * 100

    gauge = render(used_pct, cached_pct, soft, warn, forced)

    if used_pct > 100:
        # The window is wrong, not the session. Say which, rather than drawing a
        # full red bar and leaving the reader to guess.
        pre = (os.environ.get("SELF_COMPACT_PREFIX") or "")
        return (f"{pre}{DIM}{label}{RESET} {RED}{gauge.text}{RESET} {RED}window looks wrong{RESET} "
                f"{DIM}{_human(used)} used vs {_human(window)} assumed "
                f"({ctx.source}) -- set SELF_COMPACT_WINDOW{RESET}")

    colour = RED if used_pct >= forced else YELLOW if used_pct >= warn else GREEN
    parts = []
    # A machine may already have its own status line (a hostname banner, say).
    # Carrying that as a prefix keeps the gauge additive, so adopting it never
    # costs you something you already had.
    prefix = os.environ.get("SELF_COMPACT_PREFIX")
    if prefix:
        parts.append(prefix)
    parts += [
        f"{DIM}{label}{RESET}",
        f"{colour}{gauge.text}{RESET}",
        f"{DIM}{_human(used)}/{_human(window)}{RESET}",
        f"{DIM}cache {_cache_pct(ctx.usage.cache_hit_pct)}{RESET}",
    ]
    if ctx.usage.cache_creation:
        parts.append(f"{DIM}+{_human(ctx.usage.cache_creation)} w{RESET}")
    cost = payload.get("cost")
    if isinstance(cost, dict) and isinstance(cost.get("total_cost_usd"), (int, float)):
        parts.append(f"{DIM}${cost['total_cost_usd']:,.2f}{RESET}")
    rl = _rate_limits(payload)
    if rl:
        parts.append(f"{DIM}{rl}{RESET}")
    return " ".join(parts)


def main() -> int:
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass
    debug = os.environ.get("SELF_COMPACT_DEBUG")
    if debug:
        try:
            with open(debug, "w") as fh:
                fh.write(raw)
        except Exception:
            pass
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    try:
        print(build_line(payload))
    except Exception as exc:
        print(f"{DIM}context gauge unavailable ({type(exc).__name__}){RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
