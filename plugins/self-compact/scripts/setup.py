#!/usr/bin/env python3
"""Install/configure the self-compact plugin without replacing unrelated settings."""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path
import self_compact as engine

BEGIN = "# BEGIN self-compact managed settings"
END = "# END self-compact managed settings"
NATIVE_KEYS = ("model_auto_compact_token_limit", "model_auto_compact_token_limit_scope")


def remember_native(old, limit):
    import tomllib
    path = engine.data_root() / "native-settings.json"
    if path.exists():
        state = json.loads(path.read_text())
    else:
        parsed = tomllib.loads(old)
        if BEGIN in old:
            raise ValueError("Managed settings exist without a restoration record; restore your original settings before installing")
        state = {"previous": {key: parsed[key] for key in NATIVE_KEYS if key in parsed}}
    state["managed"] = {NATIVE_KEYS[0]: limit, NATIVE_KEYS[1]: "total"}
    engine.atomic_write(path, (json.dumps(state, indent=2) + "\n").encode())


def restore_native(text, state):
    import tomllib
    pattern = re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?"
    match = re.search(pattern, text, flags=re.S)
    if not match:
        return text
    current = tomllib.loads(match.group())
    if any(current.get(key) != state["managed"].get(key) for key in NATIVE_KEYS):
        raise ValueError("Managed native settings were edited; leaving them unchanged. Remove the marked block manually if desired.")
    remaining = re.sub(pattern, "", text, flags=re.S).lstrip("\n")
    parsed = tomllib.loads(remaining)
    if any(key in parsed for key in NATIVE_KEYS):
        raise ValueError("Native settings were added outside the managed block; leaving configuration unchanged")
    restored = "".join(f"{key} = {json.dumps(value)}\n" for key, value in state["previous"].items()) + remaining
    tomllib.loads(restored)
    return restored


def uninstall():
    subprocess.run(["codex", "plugin", "remove", "self-compact@self-compact-local"], check=True)
    # Keep the marketplace registration: removing a plugin does not need to
    # remove a source that may be used by other installed packages.
    path = engine.data_root() / "native-settings.json"
    config = engine.home() / "config.toml"
    if path.exists():
        old = config.read_text() if config.exists() else ""
        try:
            updated = restore_native(old, json.loads(path.read_text()))
        except ValueError as error:
            print(error)
            print("Plugin removed; restoration record retained:", path)
            return
        if old != updated:
            engine.atomic_write(engine.data_root() / "backups" / f"config-{time.time_ns()}.toml", old.encode())
            engine.atomic_write(config, updated.encode())
        path.unlink()
    else:
        print("No restoration record found; native settings were left unchanged.")
    print("Self-compact uninstalled. Restart Codex. Saved notes and preferences are retained.")


def update_native(text, limit):
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S).lstrip("\n")
    lines = text.splitlines(keepends=True)
    root = True
    kept = []
    for line in lines:
        if line.lstrip().startswith("["):
            root = False
        if root and re.match(r"\s*model_auto_compact_token_limit(?:_scope)?\s*=", line):
            continue
        kept.append(line)
    managed = (BEGIN + "\n" + f"model_auto_compact_token_limit = {limit}\n" +
               'model_auto_compact_token_limit_scope = "total"\n' + END + "\n\n")
    return managed + "".join(kept)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["install", "configure", "uninstall", "show"])
    p.add_argument("--notice")
    p.add_argument("--warning")
    p.add_argument("--compact")
    p.add_argument("--context-window", type=int, help="Effective window reported by Codex, not the advertised raw window")
    p.add_argument("--note-instructions")
    args = p.parse_args()
    if args.command == "uninstall":
        uninstall()
        return
    if args.command == "show":
        c = engine.settings()
        print(json.dumps({"settings": c, "native_cutoff_tokens": engine.resolve(c["compact"], c["context_window"])}, indent=2))
        return
    c = engine.settings()
    for key in ("notice", "warning", "compact", "context_window", "note_instructions"):
        value = getattr(args, key)
        if value is not None:
            c[key] = value
    limits = [engine.resolve(c[k], c["context_window"]) for k in ("notice", "warning", "compact")]
    if not 0 < limits[0] < limits[1] < limits[2] <= c["context_window"] * .9:
        p.error("Require 0 < notice < warning < compact <= 90%")
    config_file = engine.home() / "config.toml"
    old = config_file.read_text() if config_file.exists() else ""
    if BEGIN in old and not (engine.data_root() / "native-settings.json").exists():
        p.error("Managed settings exist without a restoration record; restore your original settings before setup")
    updated = update_native(old, limits[2])
    # Parse before mutation. Python 3.11+ is required for the installer only.
    import tomllib
    parsed = tomllib.loads(updated)
    if parsed["model_auto_compact_token_limit"] != limits[2]:
        raise ValueError("Native configuration did not round-trip")
    if args.command == "install":
        marketplace = engine.ROOT.parents[1]
        subprocess.run(["codex", "plugin", "marketplace", "add", str(marketplace), "--json"], check=True)
        subprocess.run(["codex", "plugin", "add", "self-compact@self-compact-local", "--json"], check=True)
        # plugin installation may update config.toml; re-read before editing it.
        old = config_file.read_text() if config_file.exists() else ""
        updated = update_native(old, limits[2])
        tomllib.loads(updated)
    if old != updated:
        remember_native(old, limits[2])
        if old:
            backup = engine.data_root() / "backups" / f"config-{time.time_ns()}.toml"
            engine.atomic_write(backup, old.encode())
            print("Configuration backup:", backup)
        engine.atomic_write(config_file, updated.encode())
    engine.atomic_write(engine.data_root() / "config.json", (json.dumps(c, indent=2) + "\n").encode())
    print(f"Configured native compaction at {limits[2]:,} active-context tokens.")
    print("Start a new codex session. Run /hooks and review/trust the self-compact hooks once.")
    print("No trust bypass has been enabled. Config changes apply on the next CLI start.")


if __name__ == "__main__":
    main()
