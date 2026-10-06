# Self-compact for Pi and Codex CLI

This private repository also exposes the Pi extension directly through its root package manifest. With GitHub access, install it using `pi install git:github.com/fnwokobia/self-compact`, then restart Pi. Pi manages the clone location. Configure personal thresholds in `~/.pi/agent/self-compact/config.json`; see [Pi documentation](pi/README.md) for behavior and configuration. Building or publishing this repository does not install either extension.

The separately built **Pi extension** is documented in [pi/README.md](pi/README.md). It supports direct control of the handoff, tool lock, compaction, and continuation. Its standalone GitHub-ready source archive is [pi-self-compact-0.1.1-source.tar.gz](pi/dist/pi-self-compact-0.1.1-source.tar.gz); unpack its contents at a repository root for portable `pi install git:github.com/OWNER/REPO` distribution. Neither version is currently installed by this project.

A local plugin for the normal `codex` command. No replacement terminal, app-server companion, Justfile, API key, or npm dependencies are required. Hook runtime requires Python 3.9+ on macOS/Linux; setup requires Python 3.11+.

The plugin is packaged under `plugins/self-compact` and advertised by this repository's `.agents/plugins/marketplace.json`.

**Build-only status:** the source and tests are complete. The personal installation and native configuration changes have been rolled back. Installation below is an optional, separate action that changes Codex user configuration.

## Use

When you choose to install, install and configure:

```sh
python3 plugins/self-compact/scripts/setup.py install --context-window 258400
```

Start a new ordinary `codex` session, run `/hooks`, and review/trust the self-compact hooks. Codex requires this one-time trust step for non-managed plugin hooks. The installer does not bypass it. Existing running sessions do not pick up the new native cutoff.

Example defaults are notice **40%**, warning **55%**, compaction **65%**. These are demonstration values, not benchmark-derived recommendations. With a 258,400-token effective window, the native cutoff is **167,960 active-context tokens**.

Change thresholds without reinstalling:

```sh
python3 plugins/self-compact/scripts/setup.py configure \
  --notice '50%' --warning '65%' --compact '75%' --context-window 258400
```

Thresholds also accept absolute token counts, such as `--compact 180000`. Configuration is saved to `~/.codex/self-compact/config.json`, loaded automatically by the hooks, and kept outside the installed plugin cache so upgrades preserve it. `CODEX_HOME`, if already configured, is respected. The installer updates the native cutoff in `config.toml` and saves a backup first. Restart Codex after changing the compaction cutoff.

Customize what your note preserves:

```sh
python3 plugins/self-compact/scripts/setup.py configure \
  --note-instructions 'Preserve the goal, decisions, changed files, unfinished work, and next action. Include the test command to run next.'
```

Inspect configuration or a particular session:

```sh
python3 plugins/self-compact/scripts/self_compact.py status
python3 plugins/self-compact/scripts/self_compact.py status --session SESSION_ID
```

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

## Validation

```sh
python3 -m unittest discover -s tests -v
# Opt-in: real model usage, temporary test hooks, existing login.
python3 tests/live_cli.py
python3 tests/live_cli.py --auto-compact
```

The live test uses `--ignore-user-config` and explicit test-only hook definitions. Its hook-trust bypass is restricted to that subprocess and is never persisted or enabled by the installer. Native package discovery is checked separately through `codex plugin list`.

On 6 October 2026, 13 focused offline tests passed. A real CLI run requested and saved an agent note, then continued successfully. Another real CLI run crossed a temporary 26,000-token cutoff; at the next turn native `auto` compaction invoked `PreCompact`, saved a 6,577-byte checkpoint, completed compaction, and restored the identical SHA-256 before the model returned `CLI_PLUGIN_OK`. See `evidence/plugin-cli-auto-compaction.jsonl` for the hook trace. The live tests used temporary test thresholds; they do not establish that the example percentage defaults are optimal. The repeat-compaction guard was tested offline.

The earlier `prototype/` remains an app-server transaction experiment; it is not the plugin's implementation.

Sources: [Codex lifecycle hooks](https://learn.chatgpt.com/docs/hooks), [plugin packaging](https://developers.openai.com/plugins/build/plugins), and [native compaction configuration schema](https://learn.chatgpt.com/docs/config-schema.json).
