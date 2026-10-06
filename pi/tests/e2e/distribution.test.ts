/** Exercise the actual archives from an unrelated location, without installation. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { execFileSync } from "node:child_process";
import { RpcClient, eventsOfType, messageText } from "../harness/rpc-client.ts";
import { DEFAULT_FAKE_ENV, EXTENSION, WORKDIR, makeTestDir, scriptedArgs } from "../harness/env.ts";

test("distribution: standalone source and runtime archives load after relocation; runtime completes note-first compaction", async context => {
	const t = makeTestDir("portable-distribution");
	const temporary = mkdtempSync(join(tmpdir(), "pi-self-compact-portable-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const relocated = join(temporary, "different machine", "repository");
	const excluded = new Set(["dist", "verification", "node_modules", ".git", "__pycache__"]);
	cpSync(WORKDIR, relocated, { recursive: true, filter: source =>
		!relative(WORKDIR, source).split(/[\\/]/).some(part => excluded.has(part)) });
	execFileSync("python3", ["scripts/package.py"], { cwd: relocated,
		env: { ...process.env, npm_config_cache: join(t.dir, "npm-cache") }, stdio: "pipe" });
	const { name, version } = JSON.parse(readFileSync(join(relocated, "package.json"), "utf8"));
	for (const kind of ["source", "runtime"] as const) {
		const destination = join(temporary, `extracted-${kind}`);
		mkdirSync(destination, { recursive: true });
		const archive = join(relocated, "dist", `${name}-${version}${kind === "source" ? "-source.tar.gz" : ".tgz"}`);
		execFileSync("tar", ["-xzf", archive, "-C", destination]);
		const packageRoot = join(destination, kind === "source" ? name : "package");
		const client = new RpcClient({ cwd: t.dir,
			args: scriptedArgs(t).map(arg => arg === EXTENSION ? packageRoot : arg),
			env: { ...DEFAULT_FAKE_ENV, SC_FAKE_SCENARIO: "ignore-until-forced", SC_FAKE_TRACE: t.traceFile },
			logFile: join(t.dir, `${kind}.log`) });
		try {
			const response = await client.request({ type: "get_commands" });
			assert.equal(response.success, true);
			const commands = (response.data as { commands: Array<{ name: string }> }).commands;
			assert.equal(commands.filter(c => c.name === "self-compact-info").length, 1);
			await client.request({ type: "prompt", message: "/self-compact-info" });
			const info = await client.waitFor(e => e.type === "extension_ui_request" && /^self-compact info/.test(String(e.message)));
			assert.match(String(info.message), /configured maximum 65%/);
			assert.ok(String(info.message).includes(join(packageRoot, "config.json")));
			assert.ok(String(info.message).includes(join(packageRoot, ".pi", "self-compact", "USER_PROMPT_COMPACTION_MESSAGE.md")));
			assert.doesNotMatch(String(info.message), /REJECTED/);
			if (kind === "source") continue;
			await client.request({ type: "prompt", message: "Start the scripted work." });
			const handoff = await client.waitFor(e => e.type === "message_end" &&
				(e.message as { customType?: string })?.customType === "self-compact-handoff", 60_000);
			await client.waitFor(e => e.type === "tool_execution_end" && e.toolName === "write", 30_000,
				{ since: client.events.indexOf(handoff) });
			const trace = readFileSync(t.traceFile, "utf8").trim().split("\n").map(line => JSON.parse(line));
			const note = trace.find(row => row.plan?.toolCall?.name === "self_compact")?.plan.toolCall.arguments.note_to_self;
			assert.ok(note?.length > 10);
			assert.equal(messageText(handoff.message), note);
			assert.equal(readFileSync(join(t.dir, "result.txt"), "utf8").trim(), "done");
			const phases = eventsOfType(client.events, "entry_appended")
				.filter(e => (e.entry as { customType?: string })?.customType === "self-compact-phase")
				.map(e => (e.entry as { data: { level: string } }).data.level);
			assert.deepEqual(phases.slice(0, 3), ["notice", "warning", "forced"]);
			const compaction = eventsOfType(client.events, "compaction_end")[0];
			assert.equal(compaction?.aborted, false);
			assert.match((compaction.result as { summary: string }).summary, /FAKE-SUMMARY\[You are the context-compaction summarizer/);
		} finally { await client.close(); }
	}
});
