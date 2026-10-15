"""Resolve context usage, preferring the statusLine payload over the transcript.

Claude Code's statusLine payload carries the whole picture already. Captured from
a live session on 2026-10-11 (Claude Code 2.1.296):

    context_window.context_window_size                    1000000
    context_window.total_input_tokens                      349914
    context_window.used_percentage                             35
    context_window.current_usage.input_tokens                   2
    context_window.current_usage.cache_read_input_tokens   349600
    context_window.current_usage.cache_creation_input_tokens  312

So reading the transcript is unnecessary on a current Claude Code: the window is
authoritative rather than guessed from the model id, and the KV-cache split is
right there. The transcript reader is kept only as a fallback for payloads that
lack `context_window` (older versions), and it is the slow path -- it tails a
file that can be tens of megabytes.
"""

from __future__ import annotations
import os
from dataclasses import dataclass

from transcript import Usage, read_latest_usage

# The fallback window, used only when the payload does not carry one.
#
# 200,000 on purpose, even though many models now have 1M. The two surfaces get
# different payloads: the status line receives `context_window.context_window_size`
# and never guesses, while the Stop hook's payload carries no window at all, so on
# that surface this number is always an assumption.
#
# Guessing too SMALL overstates pressure: a 1M session reads 45% at 89k instead of 9%.
# Annoying, visible, and self-correcting once usage passes 200k (see `resolve` below).
# Guessing too LARGE understates pressure: a 200k session reads 9% at 89k when it is
# nearly half full. Silent, and never self-corrects, because observed usage is only a
# lower bound. Over-alarming is the direction you can live with.
#
# On a 1M model set SELF_COMPACT_WINDOW=1000000 and neither guess applies.
DEFAULT_WINDOW = 200_000


def env_int(name: str) -> int | None:
    """Read an int from the environment, or None. Shared by BOTH surfaces.

    These readers live here, not in either entry point, because the defect this
    module keeps producing is "one surface honours an env var and the other does
    not". statusline.py had _env_int/_env_float; hooks/stop-status.py read
    os.environ directly and raised on a non-numeric value, so a stray
    SELF_COMPACT_SOFT made the gauge vanish from web and the app while the
    terminal kept rendering. One reader, imported twice, removes the class.
    """
    try:
        return int(os.environ[name])
    except Exception:
        return None


def env_float(name: str, fallback: float) -> float:
    try:
        return float(os.environ[name])
    except Exception:
        return fallback


@dataclass
class Context:
    usage: Usage | None
    window: int
    source: str  # "payload" | "transcript" | "none"


def _int(obj, *keys, default=0):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if isinstance(cur, int) else default


def _window_from_model(payload: dict) -> int:
    model = payload.get("model")
    mid = (model.get("id") if isinstance(model, dict) else model) or ""
    mid = str(mid).lower()
    if "[1m]" in mid or "-1m" in mid:
        return 1_000_000
    # exceeds_200k_tokens is the host telling us the 200k default cannot be right.
    if payload.get("exceeds_200k_tokens"):
        return 1_000_000
    return DEFAULT_WINDOW


def resolve(payload: dict, window_override: int | None = None) -> Context:
    cw = payload.get("context_window")
    if isinstance(cw, dict):
        cur = cw.get("current_usage")
        if isinstance(cur, dict):
            usage = Usage(
                input_tokens=_int(cur, "input_tokens"),
                cache_read=_int(cur, "cache_read_input_tokens"),
                cache_creation=_int(cur, "cache_creation_input_tokens"),
                output_tokens=_int(cur, "output_tokens"),
            )
            window = window_override or _int(cw, "context_window_size") or _window_from_model(payload)
            # total_input_tokens is the host's own figure; trust it over our sum
            # when the two disagree (it accounts for anything we cannot see).
            total = _int(cw, "total_input_tokens")
            if total and total != usage.context_tokens:
                usage.input_tokens = max(0, total - usage.cache_read - usage.cache_creation)
            return Context(usage=usage, window=window, source="payload")

    usage = read_latest_usage(payload.get("transcript_path"))
    window = window_override or _window_from_model(payload)

    # Self-correct the guess. The Stop hook's payload carries neither
    # `context_window` nor a model id, so the window here is assumed, and a real
    # 1M session once rendered as "159%" against a 200k assumption.
    #
    # Observed usage is a hard lower bound: a turn that sent 318k tokens cannot
    # have come from a smaller window. Raise the assumption to meet it.
    #
    # This used to walk a WINDOW_TIERS ladder (200k, 1M). Once DEFAULT_WINDOW
    # became 1M the ladder was unreachable -- the branch could only run when usage
    # already exceeded the top tier -- and the test that covered it passed
    # vacuously. Removed rather than repaired: usage is the only evidence there is.
    if usage and not window_override and usage.context_tokens > window:
        window = usage.context_tokens

    return Context(usage=usage, window=window, source="transcript" if usage else "none")
