# Self-compact for Pi and Codex CLI

Configurable context notices, warnings, and durable handoff notes around compaction. This repository contains the Pi extension and the Codex CLI hook plugin source.

## Pi

Requires Pi 0.85.1 or a compatible later release and Node 24+.

Install:

```sh
pi install git:github.com/fnwokobia/self-compact
```

Restart Pi, then use `/self-compact-info` to inspect the loaded extension and thresholds. The extension runs automatically during normal Pi use.

Uninstall:

```sh
pi remove git:github.com/fnwokobia/self-compact
```

Restart Pi after removal. Personal thresholds and note instructions belong in `~/.pi/agent/self-compact/config.json`; see [Pi configuration and behavior](pi/README.md).

## Codex CLI

Requires macOS/Linux, Python 3.11+, Git, and a Codex CLI with plugin and lifecycle hook support. Tested with Codex CLI 0.154.0. Python runs internally; you do not launch Codex through a Python script.

Download and install once:

```sh
git clone https://github.com/fnwokobia/self-compact.git
cd self-compact
./self-compact install
```

Start Codex normally:

```sh
codex
```

On the first session, run `/hooks` and review/trust the self-compact hooks. This is required by Codex for non-managed plugin hooks. Afterward, the installed plugin runs automatically in ordinary sessions; no wrapper or repeated parameters are required.

View settings:

```sh
./self-compact show
```

Configure thresholds or note requirements:

```sh
./self-compact configure --notice '40%' --warning '55%' --compact '65%' --context-window 258400
./self-compact configure --note-instructions 'Preserve unfinished tasks, decisions, and the exact next action.'
```

Restart Codex after changing the native compaction cutoff. The context window must be the effective window reported by your Codex model. The bundled 258,400-token window and 40% / 55% / 65% thresholds are example values; configure them for your model. Absolute token thresholds are also supported.

Uninstall:

```sh
./self-compact uninstall
```

Restart Codex. Removal unregisters the plugin and restores the native compaction settings recorded before setup, while preserving unrelated settings. If you subsequently edited the managed settings, removal leaves them unchanged and reports how to finish cleanup. Saved notes, preferences, backups, and the marketplace source registration are retained.

Keep this checkout for management commands. Codex caches the installed plugin and loads it through its native plugin system. Personal settings and notes live under `~/.codex/self-compact/`, or your configured `CODEX_HOME`. No installation is performed merely by cloning this repository.

## How the versions differ

Pi directly owns tool locking, note saving, compaction, and automatic continuation. The Codex plugin coordinates Codex's native automatic compaction through lifecycle hooks; the host controls when compaction starts. It does not provide Pi's all-tools lock or identical timing. See [Codex behavior and limits](plugins/self-compact/README.md).

The public source tree contains runtime code, configuration, prompts, packaging support, and documentation. Development tests, prototypes, research notes, and generated session evidence are excluded from the current tree.

## Attribution

The Pi lifecycle engine is adapted from [Indy Dev Dan's self-compact-pi-agent](https://github.com/disler/self-compact-pi-agent). Its MIT license and change attribution are included in [pi/LICENSE](pi/LICENSE) and [pi/NOTICE.md](pi/NOTICE.md).
