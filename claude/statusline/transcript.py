"""Read the live context figures out of a Claude Code transcript.

Claude Code hands a statusLine script a JSON payload containing `transcript_path`,
a JSONL file. Each `type: "assistant"` entry carries `message.usage`, verified
against Claude Code 2.1.292:

    input_tokens                 2
    cache_creation_input_tokens  1717
    cache_read_input_tokens      386452
    output_tokens                783

The context actually sent for a turn is the sum of the three input figures; most
of it is normally served from the KV cache, which is the number this module
exists to surface. Pi's own gauge shows only the cached *read* share
(`last?.cacheRead`); Claude Code additionally reports what it cost to *write*
the cache that turn, so we carry both.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass

# Read the tail rather than the whole file: a long session's transcript is
# megabytes, and a statusline re-renders constantly.
TAIL_BYTES = 512 * 1024


@dataclass
class Usage:
    input_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    output_tokens: int = 0

    @property
    def context_tokens(self) -> int:
        """What was actually sent as context for the last turn."""
        return self.input_tokens + self.cache_read + self.cache_creation

    @property
    def cache_hit_pct(self) -> float:
        total = self.context_tokens
        return (self.cache_read / total * 100) if total else 0.0


def _iter_tail_lines(path: str):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > TAIL_BYTES:
            fh.seek(size - TAIL_BYTES)
            fh.readline()  # discard the partial line we landed in
        for raw in fh:
            yield raw


def read_latest_usage(path: str | None) -> Usage | None:
    """Last main-chain assistant usage, or None when it cannot be determined.

    Never raises: a statusline that throws takes the status bar down with it.
    """
    if not path or not os.path.isfile(path):
        return None
    latest = None
    try:
        for raw in _iter_tail_lines(path):
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            # Subagent turns have their own context; they are not this session's.
            if entry.get("isSidechain"):
                continue
            usage = (entry.get("message") or {}).get("usage")
            if not isinstance(usage, dict):
                continue
            latest = Usage(
                input_tokens=int(usage.get("input_tokens") or 0),
                cache_read=int(usage.get("cache_read_input_tokens") or 0),
                cache_creation=int(usage.get("cache_creation_input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
            )
    except Exception:
        return latest
    return latest
