#!/usr/bin/env python3
"""Throwaway Codex app-server experiment. No dependencies or global config edits.

--demo: offline failure/success exercise. --probe: real runtime, no model calls.
--live: new scratch session, model-authored note, real compaction and continuation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent


class Controller:
    def __init__(self, folder, config):
        self.folder = Path(folder)
        self.config = config
        self.note = None
        self.phase = "working"
        self.cycle = 0
        self.events = []
        self.announced = 0

    def log(self, event, **data):
        entry = {"sequence": len(self.events) + 1, "event": event, **data}
        self.events.append(entry)
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / "events.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")
        print(json.dumps(entry), flush=True)

    def usage(self, tokens, window):
        if not window:
            return
        def resolve(spec):
            return round(float(spec[:-1]) / 100 * window) if str(spec).endswith("%") else float(spec)
        thresholds = [resolve(self.config[k]) for k in ("notice", "warning", "compact")]
        if not 0 < thresholds[0] < thresholds[1] < thresholds[2] <= window * .9:
            raise ValueError("Require 0 < notice < warning < compact <= 90% of model window")
        level = sum(tokens >= limit for limit in thresholds)
        if level > self.announced:
            self.announced = level
            self.log("threshold", phase=["working", "notice", "warning", "handoff_required"][level],
                     used_tokens=tokens, window=window, percent=round(tokens / window * 100, 2))
        return level

    def save_note(self, note):
        if self.phase not in ("working", "failed"):
            raise ValueError("A handoff is already pending")
        if not isinstance(note, str) or not note.strip() or len(note) > self.config["max_note_chars"]:
            raise ValueError("Note must be nonblank and within configured size limit")
        # Rename only after fsync: compaction cannot start on a partial write.
        temp = self.folder / "note.pending"
        self.folder.mkdir(parents=True, exist_ok=True)
        with temp.open("w", encoding="utf-8", newline="") as f:
            f.write(note)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, self.folder / "note.txt")
        if (self.folder / "note.txt").read_bytes() != note.encode("utf-8"):
            raise ValueError("Saved note verification failed")
        self.note = note
        self.phase = "note_saved"
        self.log("note_saved", chars=len(note), sha256=hashlib.sha256(note.encode()).hexdigest())

    def begin_compact(self):
        if self.phase != "note_saved" or self.note is None:
            raise ValueError("Compaction requires a successfully saved note")
        self.phase = "compacting"
        self.log("compaction_requested")

    def compact_finished(self, success):
        if self.phase != "compacting":
            raise ValueError("No compaction in progress")
        self.phase = "ready" if success else "failed"
        self.log("compaction_completed" if success else "compaction_failed", note_retained=True)

    def handoff(self):
        if self.phase != "ready":
            raise ValueError("Cannot restore before successful compaction")
        saved = (self.folder / "note.txt").read_bytes()
        if saved != self.note.encode("utf-8"):
            raise ValueError("Note changed since save")
        self.log("note_restored", sha256=hashlib.sha256(saved).hexdigest())
        return saved.decode("utf-8")


class AppServer:
    def __init__(self, controller):
        self.controller = controller
        self.messages = queue.Queue()
        self.seq = 0
        self.thread_id = None
        self.turns = {}
        self.compaction_item = False
        self.early_compaction = False
        self.agent_text = []
        self.usage_seen = False
        self.proc = subprocess.Popen(
            ["codex", "app-server", "--stdio", "-c", "features.apps=false", "-c", "features.shell_tool=false"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.stderr, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            try:
                self.messages.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        self.messages.put({"closed": True})

    def stderr(self):
        # Preserve diagnostics locally; never print credentials/config responses.
        with (self.controller.folder / "server.stderr.log").open("w") as f:
            for line in self.proc.stderr:
                f.write(line)
                f.flush()

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + "\n")
        self.proc.stdin.flush()

    def event(self, m):
        method, params = m.get("method", ""), m.get("params", {})
        if "id" in m and method:
            if method == "item/tool/call":
                try:
                    if params.get("tool") != "self_compact" or params.get("threadId") != self.thread_id:
                        raise ValueError("Unexpected tool or thread")
                    args = params.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    self.controller.save_note(args.get("note_to_self"))
                    self.controller.log("tool_returned", tool="self_compact")
                    result = {"success": True, "contentItems": [{"type": "inputText", "text":
                        "NOTE_SAVED. Compaction is queued until this turn ends. Finish this turn now with NOTE_SAVED. Do not call any more tools."}]}
                except (ValueError, OSError) as e:
                    result = {"success": False, "contentItems": [{"type": "inputText", "text": str(e)}]}
                self.send({"id": m["id"], "result": result})
            else:
                self.send({"id": m["id"], "error": {"code": -32601, "message": "Prototype declines other server requests"}})
            return
        if params.get("threadId") != self.thread_id:
            return
        if method == "thread/tokenUsage/updated":
            u = params["tokenUsage"]
            self.usage_seen = True
            # 'last' is current usage; 'total' is cumulative session expenditure.
            self.controller.usage(u["last"]["totalTokens"], u.get("modelContextWindow"))
        elif method == "item/started" and params.get("item", {}).get("type") == "contextCompaction":
            if self.controller.phase != "compacting":
                self.early_compaction = True
                self.controller.log("unexpected_native_compaction", phase=self.controller.phase)
        elif method == "item/completed":
            item = params.get("item", {})
            if item.get("type") == "contextCompaction":
                self.compaction_item = True
                self.controller.log("compaction_item_completed")
            elif item.get("type") == "agentMessage":
                self.agent_text.append(item.get("text", ""))
        elif method == "turn/completed":
            turn = params["turn"]
            self.turns[turn["id"]] = turn
            self.controller.log("turn_completed", turn_id=turn["id"], status=turn["status"])

    def pump(self, seconds=120):
        try:
            m = self.messages.get(timeout=seconds)
        except queue.Empty:
            raise TimeoutError("Timed out waiting for Codex; note remains on disk")
        if m.get("closed"):
            raise RuntimeError("App server exited; inspect server.stderr.log")
        self.event(m)
        return m

    def request(self, method, params, seconds=120):
        self.seq += 1
        request_id = self.seq
        self.send({"id": request_id, "method": method, "params": params})
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            m = self.pump(max(.1, until - time.monotonic()))
            if m.get("id") == request_id and "method" not in m:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
        raise TimeoutError(method)

    def wait_turn(self, turn_id, seconds=180):
        until = time.monotonic() + seconds
        while turn_id not in self.turns:
            self.pump(max(.1, until - time.monotonic()))
            if time.monotonic() >= until:
                raise TimeoutError("Turn completion timed out")
        turn = self.turns[turn_id]
        if turn["status"] != "completed":
            raise RuntimeError(f"Turn ended with {turn['status']}: {turn.get('error')}")

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def live(controller, probe_only=False, model=None):
    server = AppServer(controller)
    try:
        server.request("initialize", {"clientInfo": {"name": "self_compact_prototype", "version": "0.1.0"},
                                      "capabilities": {"experimentalApi": True}})
        server.send({"method": "initialized", "params": {}})
        account = server.request("account/read", {"refreshToken": False})
        controller.log("runtime_connected", authenticated=account.get("account") is not None)
        models = server.request("model/list", {})
        controller.log("available_models", models=[{"id": m.get("id"), "model": m.get("model"), "default": m.get("isDefault")} for m in models.get("data", [])])
        if probe_only:
            return
        # Prefer the server's advertised default over an unsupported local override.
        if model is None:
            default = next((m for m in models.get("data", []) if m.get("isDefault")), None)
            if default:
                model = default.get("model") or default.get("id")
        scratch = controller.folder / "workspace"
        scratch.mkdir()
        spec = {"type": "function", "name": "self_compact", "description":
                "Save a note verbatim and queue compaction after this turn ends. Include your exact next action.",
                "inputSchema": {"type": "object", "properties": {"note_to_self": {"type": "string"}},
                                "required": ["note_to_self"], "additionalProperties": False}}
        params = {"cwd": str(scratch), "ephemeral": True,
            "sandbox": "read-only", "approvalPolicy": "never", "dynamicTools": [spec],
            "config": {"model_auto_compact_token_limit": 1000000000,
                       "model_auto_compact_token_limit_scope": "total", "web_search": "disabled"},
            "developerInstructions": "This is a tiny self-compaction experiment. Use only the self_compact tool when asked. Do not use shell, files, web, apps, skills or agents. Follow the experiment's requested final output exactly."}
        if model:
            params["model"] = model
        thread = server.request("thread/start", params)
        server.thread_id = thread["thread"]["id"]
        controller.log("scratch_session_created", thread_id=server.thread_id,
                       model=thread.get("model", model),
                       native_trigger="raised for experiment; not proven disabled")
        nonce = "AFTER_COMPACTION_" + uuid.uuid4().hex[:12]
        prompt = ("We are testing your note-first compaction tool. Compose a short handoff note: goal is to prove exact continuation; "
                  "done: no real project work; next action: respond with exactly " + nonce + ". "
                  "Call self_compact once with that note. After the tool returns, finish this turn with NOTE_SAVED. "
                  "Do not output the next-action marker yet.")
        turn = server.request("turn/start", {"threadId": server.thread_id, "input": [{"type": "text", "text": prompt}]})
        server.wait_turn(turn["turn"]["id"])
        if controller.phase != "note_saved":
            raise RuntimeError("Model did not submit a valid note; no compaction requested")
        if server.early_compaction:
            raise RuntimeError("Native compaction preempted note-first sequence")
        controller.begin_compact()
        seen_turns = set(server.turns)
        server.request("thread/compact/start", {"threadId": server.thread_id})
        # The RPC ack is not completion; require a completed compaction item AND turn.
        until = time.monotonic() + 180
        while not (server.compaction_item and set(server.turns) - seen_turns):
            server.pump(max(.1, until - time.monotonic()))
            if time.monotonic() >= until:
                raise TimeoutError("Compaction completion timed out")
        completed = [server.turns[t] for t in set(server.turns) - seen_turns]
        if any(t["status"] != "completed" for t in completed):
            raise RuntimeError("Compaction turn failed")
        controller.compact_finished(True)
        note = controller.handoff()
        (controller.folder / "restored-note.txt").write_bytes(note.encode("utf-8"))
        server.agent_text.clear()
        turn = server.request("turn/start", {"threadId": server.thread_id, "input": [{"type": "text", "text": note}]})
        server.wait_turn(turn["turn"]["id"])
        reply = "\n".join(server.agent_text).strip()
        if reply != nonce:
            raise RuntimeError(f"Continuation mismatch: {reply!r}")
        controller.phase = "done"
        controller.cycle += 1
        controller.log("verified", same_live_session=True, note_exact=True, continued=True,
                       usage_events_seen=server.usage_seen, reply=reply)
    finally:
        server.close()


def demo(c):
    c.usage(40000, 100000)
    c.usage(55000, 100000)
    c.usage(65000, 100000)
    try:
        c.begin_compact()
    except ValueError as e:
        c.log("unsafe_compaction_refused", reason=str(e))
    try:
        c.save_note("   ")
    except ValueError as e:
        c.log("invalid_note_refused", reason=str(e))
    note = "Goal: prove note-first flow.\nDone: prototype only.\nNEXT ACTION: continue from this exact note.\n"
    c.save_note(note)
    c.begin_compact()
    c.compact_finished(False)
    c.save_note(note)
    c.begin_compact()
    c.compact_finished(True)
    restored = c.handoff()
    if restored != note:
        raise RuntimeError("Note mismatch")
    c.log("offline_verified", note_exact=True, failure_retained_note=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", help="Optional model for the scratch experiment only")
    args = parser.parse_args()
    folder = args.output or Path(tempfile.mkdtemp(prefix="self-compact-PROTOTYPE-"))
    folder.mkdir(parents=True, exist_ok=True)
    c = Controller(folder, json.loads(args.config.read_text()))
    try:
        if args.live or args.probe:
            live(c, args.probe, args.model)
        else:
            demo(c)
    except Exception as e:
        c.log("experiment_failed", reason=str(e), note_retained=c.note is not None)
        raise SystemExit(1)
    finally:
        print("Artifacts:", folder, flush=True)


if __name__ == "__main__":
    main()
