# Pi self-compact extension

A portable Pi extension package that saves a handoff note, compacts context, and resumes automatically at configurable thresholds. No fixed filesystem location, Justfile, or build step is required to use it.

Adapted from [Indy Dev Dan's MIT-licensed engine](https://github.com/disler/self-compact-pi-agent), with automatic JSON configuration and a Pi package manifest. See `NOTICE.md` and `LICENSE`.

## Configuration loads automatically

The included `config.json` contains example thresholds:

```json
{
  "notice": "40%",
  "warning": "55%",
  "compact": "65%"
}
```

These are demonstration values, not benchmark-derived defaults. The upstream built-in fallback uses 10% / 20% / 30%; our bundled JSON overrides those values on load.

The extension reads configuration on startup, session recovery, or `/reload`, in this order:

1. Package `config.json`.
2. User `~/.pi/agent/self-compact/config.json`, if present.
3. Project `<working directory>/.pi/self-compact/config.json`, if present.
4. Explicit CLI threshold overrides.

Each JSON file can override only the fields you want. If `PI_CODING_AGENT_DIR` is already set, its directory replaces `~/.pi/agent` for the user configuration. Nothing writes to these configuration files automatically. The extension does not read `.env` or change provider authentication.

`--self-compact-config /absolute/path/config.json` replaces the project layer with an explicit file. A missing explicit file, invalid JSON, unknown keys, bad thresholds, or an empty prompt causes a visible rejection; tools remain blocked until configuration is fixed and reloaded.

Tokens, `k`/`m` suffixes, percentages, and numeric token counts are supported. Percentages are re-resolved against the active model's window when you change models. The direct `compact` maximum must be at or above `warning` and no higher than 90% of that window. For the legacy warning-plus-buffer formulation, use `buffer` instead of `compact`; do not put both in one JSON file. A CLI `--compact-buffer` overrides the JSON maximum.

Optional customization:

```json
{
  "notice": "30%",
  "warning": "50%",
  "compact": "60%",
  "noteInstructions": "Include the exact next test command and preserve unfinished tasks. Mark completed work clearly.",
  "compactionPrompt": "Summarize the goal, constraints, verified work, decisions, and next steps. Preserve paths and pending actions."
}
```

`compactionPrompt` is optional literal summarizer system text. `--compact-prompt` overrides it. Otherwise the extension loads editable prompt files, first from project `.pi/self-compact/`, then from the package's `.pi/self-compact/`, then built-in text:

- `USER_PROMPT_SOFT_SELF_COMPACT.md`
- `USER_PROMPT_WARNING_SELF_COMPACT.md`
- `USER_PROMPT_COMPACTION_MESSAGE.md`
- Optional `USER_PROMPT_SUMMARY_INSTRUCTIONS.md`

## Behavior

- A live footer shows the model, current usage, cached tokens, threshold markers, phase, and cycle.
- `view_context` exposes the current numbers to the agent.
- Notice and warning guidance is injected transiently into model requests; crossings are shown to you.
- At the hard cutoff, ordinary tools are blocked. `self_compact` and `view_context` remain available.
- The agent calls `self_compact({note_to_self: "..."})`. The extension validates and journals the note before ending the run.
- Compaction starts only after the agent is idle and uses your summary prompt.
- On success, the exact note returns as the next message and starts continuation automatically; tools are restored.
- Failure/cancellation keeps the saved note and lock. Retries, reload, session resume, and tree recovery preserve the transaction. Completed handoffs are not replayed.
- `/self-compact-info` shows configuration sources, thresholds, usage, note status, and cycle without a model request.
- `/self-compact-now` requests a checkpoint or retries a pending note. Pi's built-in `/compact` remains available as a manual escape hatch; a manual compaction without a note does not invent one.

This retains upstream behavior: the agent may compact voluntarily at the warning or earlier. The maximum forces the agent to use the handoff tool; it does not compact independently without a note. If no history lies outside Pi's retained recent tokens, the extension avoids locking itself into a "nothing to compact" loop. Native overflow/automatic compaction is intercepted while this extension owns the handoff, so leave enough headroom for generating the note. A tool result can overshoot a threshold; it is not a hard token ceiling.

## Install from GitHub

Requires Pi 0.85.1 or a compatible later version and Node 24+. Use your existing Pi model/provider authentication.

Once this standalone package is uploaded to a GitHub repository, anyone can install it with:

```sh
pi install git:github.com/OWNER/pi-self-compact
```

Replace `OWNER/pi-self-compact` with the actual repository. That is a template, not an existing published repository. Pi clones the repository into its own managed package directory and registers the extension. Users do not reproduce the author's directory structure. Restart Pi, then enter `/self-compact-info` to confirm the extension and thresholds loaded.

For a tagged release:

```sh
pi install git:github.com/OWNER/pi-self-compact@v0.1.1
```

To try the GitHub package for one session, use `pi -e git:github.com/OWNER/pi-self-compact`. To uninstall it, use `pi remove git:github.com/OWNER/pi-self-compact`.

Keep personal configuration in `~/.pi/agent/self-compact/config.json` or project `.pi/self-compact/config.json`, so replacing or updating the package preserves your preferences. No threshold flags are needed on each launch. Avoid loading two self-compaction extensions in one session.

## Share this package

`dist/pi-self-compact-0.1.1-source.tar.gz` is a standalone repository archive. Extract it anywhere; its top-level `pi-self-compact/` folder contains the manifest, extension, prompts, configuration, MIT license, tests, and packaging script. Upload **the contents of that folder to your GitHub repository root**, including the hidden `.pi/` folder. Do not upload the enclosing Codex project or nest this package under another `pi/` directory. No owner-specific paths or credentials are included.

For direct file sharing without GitHub:

```sh
tar -xzf pi-self-compact-0.1.1-source.tar.gz
pi install ./pi-self-compact
```

A local installation registers that chosen folder in place. Keep it there; the folder can be anywhere. For a one-session local trial, use `pi -e ./pi-self-compact` instead.

The smaller `dist/pi-self-compact-0.1.1.tgz` is an npm-format runtime archive, also self-contained. Its extracted root is named `package/`; register that extracted folder with `pi install ./package`. Neither archive needs npm dependencies installed for local loading: Pi supplies the extension runtime modules.

This package is ready for GitHub distribution; it has not been uploaded, published to npm, or installed on your machine. If you later publish it to npm under an available name, Pi also supports `pi install npm:PACKAGE_NAME`.

## Verification

```sh
cd pi-self-compact
npm test
```

Tests use the real installed Pi CLI in RPC mode with an offline scripted provider and isolated test profiles under `verification/`. They neither install the extension nor load your credentials. They cover file loading, CLI precedence, model-window changes, threshold crossings, tool locking, sibling tool calls, exact note preservation, continuation, two cycles, failed compaction, and recovery. Unit tests check footer rendering; interactive terminal rendering and paid-model behavior are not claimed by these offline tests.

Build verification on 6 October 2026: **35 unit tests and 12 offline integration tests passed together** on Pi 0.85.1 and Node 26.7.0. The distribution test builds the archives from a relocated checkout, extracts both into unrelated directories, verifies automatic configuration and shipped prompt loading, and runs the runtime archive through threshold crossings, exact note preservation, compaction, and automatic continuation. No personal Pi installation is performed.

For distribution, the package includes a `pi.extensions` manifest and can be packed as a tarball without installing dependencies. Pi supplies its core runtime packages.

## Build distribution archives

From the package root, run `npm run package` (Python 3 is required only for packaging). This creates both archives under `dist/`, excluding test output, dependency directories, and Git history. The source archive can become a standalone GitHub repository; the npm archive contains runtime files only.
