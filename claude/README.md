# Self-compact for Claude Code — the context gauge

A status line that shows how full the context window is **and how much of it is served
from the KV cache**, plus a Stop hook that puts the same gauge where the status line
cannot reach: Claude on the web and in the desktop app.

```
Opus 5 [#######----~--!-|---] 35%  349.9k/1.00M  cache 99.9%  +312 w  $91.51  5h 2% 7d 12%
```

`#` is the cached share, `=` is used beyond the cache, `-` is free. `~` `!` `|` are the
notice / warning / forced threshold markers. `+312 w` is cache *creation* — what it cost
to write the cache this turn.

## What this is, and is not

This is the **gauge half** of the self-compact idea, ported to Claude Code. It does not
compact anything.

The Pi extension in `../pi` hands the agent a gauge, escalating pressure, and a
self-written handoff note, then calls `ctx.compact()` at a clean checkpoint. **Claude
Code has no equivalent of that call** — no hook can trigger compaction (`anthropics/
claude-code#39275`), and `PreCompact` receives `custom_instructions: None` on an
automatic compaction, so a hook cannot steer the summary either. Both verified against
Claude Code 2.1.292.

So the ladder does not port. What does port is the part you can see: the bar, the cache
share, and the thresholds. The remaining pieces, for anyone who wants to build them, are
`PreCompact` writing state to disk and `SessionStart` with `source: "compact"` reading
it back as `additionalContext` (capped at 10,000 characters).

## Install

```jsonc
// ~/.claude/settings.json
{
  "statusLine": { "type": "command", "command": "<abs>/claude/statusline/statusline.py" },
  "hooks": {
    "Stop": [{ "matcher": "", "hooks": [
      { "type": "command", "command": "<abs>/claude/hooks/stop-status.py" }
    ]}]
  }
}
```

The Stop hook is optional. Add it if you want the gauge on claude.ai and in the desktop
app; skip it if you only work in a terminal.

Requires `python3` (3.8+) and nothing else. No packages, no daemon, no network access.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SELF_COMPACT_WINDOW` | `200000` | the context window in tokens. **Set this to `1000000` on a 1M model** |
| `SELF_COMPACT_SOFT` | `60` | notice marker, percent of window |
| `SELF_COMPACT_WARN` | `75` | warning marker |
| `SELF_COMPACT_FORCED` | `85` | forced marker |
| `SELF_COMPACT_PREFIX` | — | text printed before the gauge, if the machine already has a banner |
| `SELF_COMPACT_RATELIMITS` | on | `0` hides the 5h/7d quota figures |
| `SELF_COMPACT_STOP_QUIET` | off | `1` silences the Stop hook |
| `SELF_COMPACT_DEBUG` | off | path to dump the raw payload, useful for checking the schema |

**Why the window defaults to 200,000 when many models have 1M.** The two surfaces get
different payloads. The status line receives `context_window.context_window_size` and
never guesses. The Stop hook's payload carries no window at all, so there the number is
always an assumption — and the two guesses fail differently. Too small overstates
pressure (a 1M session reads 45% at 89k instead of 9%): annoying, visible, and
self-correcting once usage passes 200k. Too large understates it (a 200k session reads
9% when it is nearly half full): silent, and never self-correcting, because observed
usage is only a lower bound. Over-alarming is the direction you can live with. Set
`SELF_COMPACT_WINDOW=1000000` and neither guess applies.

Thresholds default to 60/75/85 rather than the Pi extension's 10/20/30, which are tuned
for out-loop agents that must compact long before the wall. An interactive Claude Code
session auto-compacts near the top anyway.

## Two behaviours worth knowing

**The Stop hook lags one turn**, and is silent on a session's first turn. It runs before
the turn's usage reaches the transcript — measured: the hook fired three seconds *after*
the newer usage was timestamped and still read the previous turn, so polling cannot
close it. Output is labelled `(prev turn)` because the cache share in particular can
swing from 10% to 99% between consecutive turns. The status line has no such lag.

**The status line is terminal-only.** It is a TUI construct and does not run under
`claude -p`. That is the whole reason the Stop hook exists.

## Tests

```sh
claude/scripts/validate
```

55 tests, no third-party dependencies, verified on macOS and Linux and from a read-only
install. The fixtures pin real captured payloads for both surfaces, because every
assumption made about their shape before capturing one turned out to be wrong.

## Credits

The 20-cell context bar is a port of `apps/self-compact/extensions/self-compact/
context-bar.ts` from [disler/self-compact-pi-agent](https://github.com/disler/self-compact-pi-agent)
(MIT), including its cached-share semantics. `claude/statusline/tests/test_bar.py`
asserts this port reproduces that renderer's documented output byte for byte.
