# Codex CLI self-compact plugin

Install from the repository root with `./self-compact install`. Start ordinary `codex` sessions after installation; the hooks run automatically. Python is the internal hook runtime, not a command users type to launch Codex. See the [main README](../../README.md) for installation, configuration, and removal.

## Behavior

- `SessionStart` automatically loads plugin instructions and state.
- Prompt, tool, and stop hooks inspect current context usage from the session transcript's most recent token event. Cumulative spending and file size are not used as context estimates.
- Threshold crossings produce CLI warnings once per compaction cycle. Hooks run at lifecycle points; this is not a continuously updating footer.
- At the warning threshold, the `Stop` hook asks the agent for a short internal handoff note. A second hook saves that response, then asks the agent to continue the original task. This can display the internal note in terminal output. Requests are bounded to avoid continuation loops.
- Codex's **native automatic compaction** owns the trigger. Setup applies `model_auto_compact_token_limit` with `model_auto_compact_token_limit_scope = "total"`.
- Immediately before every manual or automatic compaction, `PreCompact` saves and verifies a current local checkpoint containing recent transcript excerpts and any earlier agent note. If the agent hasn't written a note yet, this checkpoint is the fallback. It is explicitly labeled as a local checkpoint, not an agent-authored summary.
- If no usable checkpoint exists or its write/verification fails, the hook returns `continue: false` to stop compaction. Hook crashes/timeouts themselves remain subject to Codex's advisory error behavior.
- After compaction, `SessionStart` with source `compact` injects the saved checkpoint into the next model request. State is reset for the next cycle, and old token telemetry is ignored until a new event arrives.
- If a cycle leaves context above the cutoff and barely reduces it, a guard stops a repeated automatic-compaction attempt with an actionable message. Manual compaction remains available.

Notes use atomic rename, file and directory fsync, private temporary file permissions, and SHA-256 verification. Per-session file locks prevent concurrent hooks from corrupting state. Notes and event logs remain under `~/.codex/self-compact/sessions/`; session ids are hashed into safe directory names. Separate agent-note and checkpoint files preserve the original agent response even when the checkpoint excerpt is bounded.

## Practical limits

The CLI does not expose a plugin hook that directly calls compaction. This implementation configures and coordinates native compaction instead. Native compaction checks run at host-defined safe points; crossing the configured limit is not an exact hard stop. A final response may end before compaction and compaction may then happen at the next turn. The plugin does not deny project tools or claim to provide an all-tools lock.

Percentage warnings use the effective window from observed telemetry. The native cutoff is converted to tokens at setup, so rerun configure if you switch to a model with a different effective window. The plugin reports a mismatch instead of silently assuming the cutoff follows that model. Higher-priority profiles, project configuration, and command-line overrides can override the native cutoff.

The transcript parser targets the observed Codex CLI 0.154.0 JSONL format, which OpenAI documents as unstable. Missing telemetry is reported; it is never replaced with a fabricated percentage. Local checkpoints contain bounded recent excerpts, not a complete transcript. Codex may spill unusually large restored context to a file.

