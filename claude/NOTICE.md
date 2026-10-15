# Source attribution

`statusline/bar.py` is a port of the 20-cell context bar from
[disler/self-compact-pi-agent](https://github.com/disler/self-compact-pi-agent)
(`apps/self-compact/extensions/self-compact/context-bar.ts`), MIT licensed. The cell
semantics are carried over unchanged — `#` inside the cached share, `=` beyond it, `-`
free, with `~` `!` `|` threshold markers and stronger markers winning a shared cell.
`statusline/tests/test_bar.py::test_disler_canonical_example` asserts the port
reproduces that file's own documented output, `[###~====-!-|--------] 40%`, exactly.

The upstream MIT licence is reproduced in `../pi/LICENSE`.

Everything else here is new. The control model is deliberately not ported: Pi's
extension calls `ctx.compact()` to trigger compaction at a checkpoint it chooses, and
Claude Code exposes no equivalent, so this prepares for host-driven compaction rather
than causing it.
