"""Pure 20-cell context bar renderer.

A faithful port of `apps/self-compact/extensions/self-compact/context-bar.ts`
from disler/self-compact-pi-agent (MIT). Kept pure and dependency-free so it can
be tested without a Claude Code session, exactly as the TypeScript original is.

Cell i covers (5i, 5(i+1)] percent. Used cells are `#` inside the cached share
and `=` beyond it; free cells are `-`. Threshold markers overlay the cell whose
upper bound equals the threshold percent (index ceil(pct / 5) - 1):
`~` soft, `!` warning, `|` forced. Stronger markers win the same cell
(`|` > `!` > `~`), so a zero buffer shows a single `|`.
"""

from __future__ import annotations
import math
from dataclasses import dataclass

CELLS = 20
FREE, USED, CACHED = "-", "=", "#"
MARKERS = ("~", "!", "|")  # weakest -> strongest; later wins the same cell


def _cells_for(pct: float | None) -> int:
    """How many cells a percentage fills. ceil, because cell i covers (5i, 5(i+1)]."""
    if not pct or pct <= 0:
        return 0
    return min(CELLS, math.ceil(pct / (100 / CELLS)))


def _marker_index(pct: float | None) -> int | None:
    """The cell a threshold marker overlays, or None when off-scale."""
    if pct is None or pct <= 0 or pct > 100:
        return None
    return min(CELLS - 1, math.ceil(pct / (100 / CELLS)) - 1)


@dataclass
class Bar:
    bar: str
    label: str
    text: str


def render(
    used_pct: float | None,
    cached_pct: float = 0.0,
    soft_pct: float | None = None,
    warn_pct: float | None = None,
    forced_pct: float | None = None,
) -> Bar:
    used = _cells_for(used_pct)
    cached = min(used, _cells_for(cached_pct))

    cells = [CACHED if i < cached else USED if i < used else FREE for i in range(CELLS)]

    # Stronger markers overwrite weaker ones in the same cell, so apply in order.
    for pct, mark in zip((soft_pct, warn_pct, forced_pct), MARKERS):
        idx = _marker_index(pct)
        if idx is not None:
            cells[idx] = mark

    bar = "".join(cells)
    label = "--%" if used_pct is None else f"{round(used_pct)}%"
    return Bar(bar=bar, label=label, text=f"[{bar}] {label}")
