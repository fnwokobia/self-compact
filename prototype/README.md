# Note-first Codex compaction prototype

**Verdict: the sequence works against a real Codex app server.** On 5 October 2026, Codex CLI 0.154.0 with the runtime-advertised default `gpt-6-astra` generated a note through the prototype's `self_compact` tool. The controller saved it, waited for the active turn to complete, requested compaction of that same session, waited for completion, then restored the note as the next turn. The model performed the exact next action specified in the note.

This is throwaway experimental code, not an installed desktop plugin. It answers whether a controller with app-server access can enforce **save first, compact second**.

## Try it

Open `walkthrough.html` directly, or use the running [local walkthrough](http://127.0.0.1:8769/walkthrough.html). The page is a simulation with four guided scenarios: successful handoff, saving failure, compaction failure, and a competing native trigger.

From the repository directory:

```sh
# Offline lifecycle exercise; no account or network needed.
python3 prototype/codex_compact.py --demo

# Verify the installed runtime and login; no model calls.
python3 prototype/codex_compact.py --probe

# Real experiment with existing Codex login and advertised default model.
# Generates a note, performs compaction, and continues in a new scratch session.
python3 prototype/codex_compact.py --live
```

Python's standard library and the installed `codex` command are sufficient. No Justfile, npm installation, OpenRouter keys, or modifications to global configuration are required. Live mode uses your existing Codex authentication and consumes model usage. It starts a separate ephemeral thread with read-only model tool permissions; the controller writes only its own scratch artifacts. The app server itself uses the normal Codex state directory and must have permission to initialize its SQLite state.

`--model ID` optionally selects the scratch model. `--config PATH` selects threshold settings. `--output PATH` saves artifacts in a chosen fresh directory; otherwise a clearly named temporary directory is created.

## The observed proof

See `evidence/live-events.jsonl` and the two note files. The successful run recorded:

1. `note_saved`: 232 characters, SHA-256 `b0cb417a4518be355a2f7601827a2115643b148d1ee052faab5d5c3428de9b34`.
2. `tool_returned`, then the first `turn_completed`.
3. `compaction_requested` for that same thread.
4. `compaction_item_completed` and a completed compaction turn.
5. `note_restored` with the identical hash.
6. A continuation turn producing exactly `AFTER_COMPACTION_b3a480dc3125`.

Real context-usage notifications were observed. The small live experiment did not fill the context window to test threshold-triggered warnings. Those crossings and refusal/failure states were exercised offline. The offline compaction result is simulated; the live compaction result is real.

The initial live attempt used a configured model the service rejected. The successful attempt used the default advertised by `model/list`. The script now selects that advertised default automatically unless a model is explicitly supplied.

## How it works

The agent submits its full note as the tool argument. The controller rejects empty/oversized notes, writes the note to a scratch temporary file, flushes it, atomically renames it, and verifies the saved bytes. Only then is a compaction request eligible.

The dynamic tool returns **note saved; compaction queued**. It does not claim compaction has completed. The controller waits until the active model turn ends before requesting `thread/compact/start`. An RPC acknowledgement is not enough: it waits for a completed compaction item and successful turn before restoring the original note as the next model input.

## What remains unproven

- Installing this as an ordinary plugin in an existing Codex desktop chat and obtaining authorized control of that chat's live runtime.
- Disabling or coordinating every native automatic-compaction path. The experiment raises the native threshold only in its scratch thread; it does not claim native compaction is disabled.
- A guaranteed all-tools lock, large-result overshoot behavior, multi-session/branch recovery, and repeated live cycles.
- Full automatic threshold steering: this prototype reports crossings; live mode explicitly prompts for one handoff to isolate the critical transaction.

The note-first race is solved **for compaction owned by this controller**. A competing native trigger still needs a separate integration proof. Dynamic tools are an experimental app-server API, so packaging should include version checks.

Sources: [Codex app-server API](https://learn.chatgpt.com/docs/app-server), the locally generated protocol schemas, and the captured live-run evidence.
