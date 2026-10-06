# Self-compaction feasibility review

Reviewed 5 October 2026; implementation updated 6 October 2026. A Codex CLI plugin is built, with captured real CLI hook evidence. Its personal installation and native configuration changes were rolled back to respect the build-only request; the source and tests remain. See [current implementation and optional setup](README.md). The feasibility discussion below records the earlier findings; the app-server prototype is separate from the CLI plugin.

## Codex CLI implementation update

The Pi version is now built separately under `pi/`, retaining the upstream lifecycle engine and adding automatic layered JSON configuration. See [Pi configuration and optional installation](pi/README.md). It has not been installed in the user's Pi profile.

The local `self-compact` plugin uses lifecycle hooks inside the standard CLI, current-context token telemetry from its transcript, configurable notifications, agent notes requested through `Stop`, a verified `PreCompact` checkpoint, and restoration through `SessionStart` after native automatic compaction. Setup applies the native token cutoff with full-context accounting. Native compaction and same-session continuation were verified in a real CLI run. This implementation does not depend on attaching a plugin to a desktop chat or providing a replacement terminal client. Hook trust still requires the CLI's `/hooks` review, and the native trigger's safe-point timing and transcript-format limitations still apply.

## Prototype update

A subsequent live experiment proved that an app-server client can receive an agent-authored `self_compact` note, save and verify it, wait for the active turn to end, request compaction of that same session, then restore the exact note and obtain the expected continuation. See [prototype results](prototype/README.md) and the captured evidence. Ordinary desktop-plugin access and exclusive control over native automatic compaction remain unverified.

## Decision

Build one shared configuration and handoff engine, with a Pi extension and separate Codex and Claude Code plugin adapters. Justfile is unnecessary. Pi supports the closest reproduction. Codex and Claude Code can combine native automatic compaction with configurable notices, warnings, and durable notes, but a plugin alone does not provide every capability of Pi's extension API.

The Claude target here is **Claude Code**, not the general Claude chat application or Cowork.

## What the video actually demonstrates

I reviewed the full English auto-caption transcript and video metadata, rather than visually watching the recording. Auto-captions can misrecognize names and wording.

The three agents build competing implementations of the same **Pi extension**. They are not three integrations running inside their respective coding tools. At about [16:23](https://www.youtube.com/watch?v=3b0U4_02bAE&t=983s), he launches the builders; at [19:49](https://www.youtube.com/watch?v=3b0U4_02bAE&t=1189s), he tests their Pi implementations. At [25:59](https://www.youtube.com/watch?v=3b0U4_02bAE&t=1559s), the handoff note appears separately from the summary.

The useful pattern is to expose context usage to the agent, let it choose a checkpoint after a notice, ask for a note at a warning, and restrict work at the cutoff. The video first discusses absolute token thresholds; the published source ships percentage defaults.

## Repository findings

Source: [disler/self-compact-pi-agent](https://github.com/disler/self-compact-pi-agent). MIT licensed. Reviewed the extension entry point, threshold parser, state recovery, prompt discovery, summary implementation, command runner, and test harness.

The published implementation provides:

- Notice at 10%, warning at 20%, forced phase at 30% by default. Forced = warning + buffer, capped at 90%.
- Threshold input as percentages, whole tokens, or k/m suffixes.
- `view_context()` and `self_compact({ note_to_self })` tools; info and manual-compaction commands.
- Editable notice, warning, summary-system, and summary-instruction prompt files.
- A context footer with cached/uncached usage, threshold markers, phase, and cycle count.
- A separately persisted note, restored verbatim after successful compaction, followed by autonomous continuation.
- Retry and recovery state for failures, reloads, resumed sessions, and branch changes.
- Protection against requesting compaction when the retained recent history leaves nothing to summarize.

Two source details matter when porting: the actual tool-call handler permits both `self_compact` and `view_context` during a forced phase, despite prose saying only the former; and guidance is rebuilt for each model request while its phase is active, while terminal crossing announcements are deduplicated.

The cutoff is checked at observable boundaries. A large result can jump over it; already-running calls are not undone. An uncooperative model can still refuse to call the compaction tool, so tool blocking is not an unconditional guarantee of progress.

## Removing Justfile and other unnecessary dependencies

The justfile launches Pi, forwards flags, loads `.env`, and invokes npm or shell verification scripts. No threshold logic, note storage, or compaction implementation lives in it.

An equivalent launch is:

```sh
pi -e /path/to/self-compact/self-compact.ts \
  --compact-soft-at 40% --compact-at 55% --compact-buffer 10%
```

That means notice 40%, warning 55%, forced 65%. These are an example, not a claim about optimal thresholds. Provider credentials must already be available to Pi; removing Justfile also removes its automatic `.env` loading.

The extension itself declares no npm dependencies: Pi supplies its packages at runtime. Its tests require Node 24 or newer. OpenRouter and a particular model are optional; the extension uses the provider/model configured in Pi. The plan-writing skill, model comparisons, and multi-agent build workflow in the video are development aids, not runtime requirements.

## Platform adapters

| Target | Recommended integration | Main limitation |
| --- | --- | --- |
| Pi | Package the existing extension and shared configuration | Must account for retained history, model changes, and overshoot |
| Codex local CLI/desktop | Plugin hooks and note tool, plus native token compaction limit | Hook input has no stable live context-usage field; ordinary plugin access is not equivalent to controlling the app server |
| Claude Code | Plugin hooks/note tool, status-line integration, native auto-compaction override | Native compaction owns timing; the plugin cannot replace the built-in summary system prompt |

### Codex

The installed CLI is **0.154.0**. Its generated protocol schema contains `model_auto_compact_token_limit`, `model_auto_compact_token_limit_scope`, `compact_prompt`, `PreCompact`, `PostCompact`, `thread/compact/start`, and `thread/tokenUsage/updated`. These establish interface availability, not end-to-end plugin behavior in this desktop session.

Use `model_auto_compact_token_limit` for the automatic trigger. A percentage-based configuration must resolve to tokens for the active model. Do not assume all models share a context window, or mistake lifetime token expenditure for active context size. Use the `total` scope when the user means percentage of the full active window.

Use hooks to display crossings, request a note early, and restore it through `SessionStart` with the `compact` matcher. That hook can provide context to an immediate continuation following automatic compaction. Store the note before compaction; a pre-compaction shell hook cannot make the model write a new note by itself.

For warnings inside ordinary desktop/CLI sessions, a transcript reader is a possible compatibility layer, but the transcript format is explicitly unstable. Treat unknown usage as unknown and report unsupported versions. For stable event-driven monitoring and agent-triggered compaction, use an app-server client that owns or has authorized access to the live runtime. Starting another app server against the same saved thread is not a safe substitute for controlling the existing session.

Codex tool hooks do not cover every hosted or specialized tool path, so they cannot reproduce an absolute all-tools lock. Native compaction should remain the fallback. Hook installation also requires the host's trust review.

Sources: [configuration schema](https://developers.openai.com/codex/config-schema.json), [hooks](https://learn.chatgpt.com/docs/hooks), [app server](https://learn.chatgpt.com/docs/app-server), [plugin packaging](https://developers.openai.com/plugins/build/plugins).

### Claude Code

The installed version is **2.1.172**. Current documentation describes more recent capabilities, so the adapter must feature-check rather than assume all documented events exist on this installation.

The native override is `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`. Documentation describes it as a percentage of the **auto-compact window**, which should not automatically be equated to the status line's percentage of the full model window. It can lower the threshold, and only applies in sessions that compact proactively before the context limit. Verify its observed behavior on the chosen version and model.

A status-line script receives usage fields and can save a session-specific snapshot for hooks. Preserve an existing status line by composing with it. Hooks provide warnings and request an agent-authored note; `SessionStart` after compaction can restore that note. Use compact instructions to guide the summary, while keeping the note independent.

A plugin cannot simply set arbitrary host settings through its bundled `settings.json`: current plugin documentation limits applied defaults to selected fields. Configure the native environment override and main status-line integration separately during setup. A value set only inside a hook subprocess does not configure the running Claude process.

Do not advertise an MCP tool as invoking `/compact` internally unless the host supplies a supported control interface. A bare MCP server cannot execute a host slash command merely by returning its text.

Sources: [environment variables](https://code.claude.com/docs/en/env-vars), [status line](https://code.claude.com/docs/en/statusline), [hooks](https://code.claude.com/docs/en/hooks), [plugin manifest](https://code.claude.com/docs/en/plugins-reference), [compact instructions](https://code.claude.com/docs/en/how-claude-code-works).

## Shared implementation contract

Use one JSON config with `notice`, `warning`, and `compact` thresholds, accepting token counts or percentages; optional per-model overrides; editable prompts; and notification preferences. Keep runtime state separate and keyed by host, session, branch where available, and compaction cycle.

At notice, notify once per cycle. At warning, ask the agent to finish its current small step and save a note containing goal, constraints, completed work, current work, decisions, verified results, blockers, and exact next action. Keep the note bounded, store it atomically, and preserve the original text independently of the generated summary.

At the cutoff, Pi can enforce the note/compaction transaction. Codex and Claude Code should rely on the configured native trigger for an initial plugin implementation. Do not create a tool-denial loop that blocks the note-saving operation or expects a compaction API the host does not expose.

After success, restore the note before continuation and acknowledge its handoff id. Reset notices once per cycle. On failure, retain the note, bound retries, and expose a recovery command. If a large result crosses both warning and cutoff, use the latest saved checkpoint and report that no fresh agent-authored note was obtained.

## Validation and rollout

The upstream **30 unit tests and 10 deterministic integration tests passed** using npm directly, demonstrating that Justfile is unnecessary. Integration tests ran against the installed Pi 0.85.1 with an isolated temporary profile and a scripted provider. They covered thresholds, locking, exact note preservation, continuation, two cycles, validation, and failure/resume recovery. The first integration attempt hit a sandbox restriction on Pi's default credential lock; the isolated run completed successfully. No paid model runs were performed.

Implement Pi first as the reference behavior, then Claude Code's native-trigger plugin, then Codex's native-trigger plugin with an explicit telemetry compatibility check. Add an app-server companion only if exact Codex event-driven control is required. Validate real host behavior before calling either plugin fully equivalent to Pi.

Acceptance checks: threshold crossings, large-result overshoot, exact note round-trip, automatic continuation, repeated cycles, failure/cancel/restart, model switches, concurrent sessions, missing telemetry, existing status-line preservation, and avoidance of immediate repeated compaction.
