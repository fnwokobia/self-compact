import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfiguration, resolveConfiguredThresholds } from "../../extensions/self-compact/config.ts";

function fixture(run: (root: string, write: (relative: string, value: unknown) => void) => void) {
	const root = mkdtempSync(join(tmpdir(), "pi-self-compact-config-"));
	const write = (relative: string, value: unknown) => {
		const p = join(root, relative);
		mkdirSync(join(p, ".."), { recursive: true });
		writeFileSync(p, JSON.stringify(value));
	};
	try { run(root, write); }
	finally { rmSync(root, { recursive: true, force: true }); }
}

test("JSON loads automatically with package/user/project precedence and partial overrides", () => fixture((root, write) => {
	write("package/config.json", { notice: "40%", warning: "55%", compact: "65%" });
	write("agent/self-compact/config.json", { notice: "30%", noteInstructions: "Include the next test command." });
	write("project/.pi/self-compact/config.json", { warning: "50%" });
	const c = loadConfiguration({ cwd: join(root, "project"), agentDir: join(root, "agent"), packageRoot: join(root, "package") });
	assert.equal(c.specs.softAt, "30%");
	assert.equal(c.specs.at, "50%");
	assert.equal(c.forcedAt, "65%");
	assert.equal(c.files.length, 3);
	assert.equal(c.noteInstructions, "Include the next test command.");
	const r = resolveConfiguredThresholds(c.specs, c.forcedAt, 100000);
	assert.equal(r.ok, true);
	if (r.ok) assert.deepEqual([r.thresholds.softTokens, r.thresholds.warnTokens, r.thresholds.forcedTokens], [30000, 50000, 65000]);
}));

test("explicit config replaces project layer; CLI buffer overrides the configured maximum", () => fixture((root, write) => {
	write("package/config.json", { notice: "40%", warning: "55%", compact: "65%" });
	write("project/.pi/self-compact/config.json", { notice: "30%" });
	write("project/custom.json", { warning: "45%", compactionPrompt: "Custom summary instructions." });
	const c = loadConfiguration({ cwd: join(root, "project"), agentDir: join(root, "agent"), packageRoot: join(root, "package"),
		flags: { config: "custom.json", softAt: "20%", buffer: "5%", prompt: "CLI prompt" } });
	assert.equal(c.specs.softAt, "20%");
	assert.equal(c.specs.at, "45%");
	assert.equal(c.specs.buffer, "5%");
	assert.equal(c.forcedAt, undefined);
	assert.equal(c.compactionPrompt, "CLI prompt");
	assert.equal(c.sources.softAt, "flag");
	assert.equal(c.files.length, 2);
}));

test("configured maximum follows model changes and supports mixed token/percentage units", () => {
	const specs = { softAt: "10k", at: "40%", buffer: "0" };
	const small = resolveConfiguredThresholds(specs, "65%", 100000);
	const large = resolveConfiguredThresholds(specs, "65%", 200000);
	assert.equal(small.ok, true); assert.equal(large.ok, true);
	if (small.ok && large.ok) assert.deepEqual([small.thresholds.forcedTokens, large.thresholds.forcedTokens], [65000, 130000]);
	const mixed = resolveConfiguredThresholds(specs, "90k", 200000);
	assert.equal(mixed.ok, true);
	if (mixed.ok) assert.equal(mixed.thresholds.bufferTokens, 10000);
	assert.equal(resolveConfiguredThresholds(specs, "95%", 100000).ok, false);
	assert.equal(resolveConfiguredThresholds(specs, "30%", 100000).ok, false);
});

test("missing explicit file and malformed configuration are rejected instead of silently falling back", () => fixture((root, write) => {
	const options = { cwd: root, agentDir: join(root, "agent"), packageRoot: join(root, "package") };
	assert.throws(() => loadConfiguration({ ...options, flags: { config: "missing.json" } }), /Cannot read/);
	for (const invalid of [{ notice: true }, { unexpected: "x" }, { compact: "60%", buffer: "5%" }, [], { compactionPrompt: " " }]) {
		write("package/config.json", invalid);
		assert.throws(() => loadConfiguration(options));
	}
	writeFileSync(join(root, "package/config.json"), "{not json}");
	assert.throws(() => loadConfiguration(options), /Invalid JSON/);
}));

test("reload reads edited config; absent files fall back to upstream defaults", () => fixture((root, write) => {
	const options = { cwd: root, agentDir: join(root, "agent"), packageRoot: join(root, "package") };
	assert.equal(loadConfiguration(options).fromDefaults, true);
	write("package/config.json", { notice: "30%", warning: "50%", compact: "60%" });
	assert.equal(loadConfiguration(options).forcedAt, "60%");
	write("package/config.json", { notice: "30%", warning: "50%", compact: "70%" });
	assert.equal(loadConfiguration(options).forcedAt, "70%");
}));
