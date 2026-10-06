/** Automatic JSON configuration. No .env loader or launcher is required. */
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { DEFAULT_SPECS, parseTokenSpec, resolveThresholds, validateSpecs, type ThresholdSpecs, type SpecSource, type ResolveResult } from "./thresholds.ts";

export interface FileConfig {
	notice?: string | number;
	warning?: string | number;
	compact?: string | number;
	buffer?: string | number;
	compactionPrompt?: string;
	noteInstructions?: string;
}

export interface LoadedConfig {
	specs: ThresholdSpecs;
	sources: { softAt: SpecSource; at: SpecSource; buffer: SpecSource };
	forcedAt?: string;
	compactionPrompt?: string;
	noteInstructions?: string;
	files: string[];
	fromDefaults: boolean;
}

function readConfig(path: string, required: boolean): FileConfig | undefined {
	let text: string;
	try { text = readFileSync(path, "utf8"); }
	catch (error) {
		if (!required && (error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
		throw new Error(`Cannot read self-compact configuration ${path}: ${error instanceof Error ? error.message : error}`);
	}
	let data: unknown;
	try { data = JSON.parse(text); }
	catch { throw new Error(`Invalid JSON in self-compact configuration: ${path}`); }
	if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error(`Expected a configuration object: ${path}`);
	const config = data as Record<string, unknown>;
	for (const key of Object.keys(config)) {
		if (!["notice", "warning", "compact", "buffer", "compactionPrompt", "noteInstructions"].includes(key)) throw new Error(`Unknown self-compact setting "${key}" in ${path}`);
	}
	if (config.compact !== undefined && config.buffer !== undefined) throw new Error(`Use compact OR buffer, not both, in ${path}`);
	for (const key of ["notice", "warning", "compact", "buffer"]) {
		const value = config[key];
		if (value !== undefined) {
			if (typeof value !== "string" && typeof value !== "number") throw new Error(`Invalid ${key} in ${path}: use tokens or a percentage`);
			parseTokenSpec(String(value), `${key} in ${path}`);
		}
	}
	if (config.compactionPrompt !== undefined && (typeof config.compactionPrompt !== "string" || !config.compactionPrompt.trim())) throw new Error(`compactionPrompt must be nonblank text in ${path}`);
	if (config.noteInstructions !== undefined && (typeof config.noteInstructions !== "string" || !config.noteInstructions.trim())) throw new Error(`noteInstructions must be nonblank text in ${path}`);
	return config as FileConfig;
}

/** Package -> user -> project (or explicit file) -> CLI. Files load on session start/reload. */
export function loadConfiguration(options: {
	cwd: string; packageRoot: string; agentDir: string;
	flags?: { softAt?: string; at?: string; buffer?: string; prompt?: string; config?: string };
}): LoadedConfig {
	const flags = options.flags ?? {};
	const result: LoadedConfig = {
		specs: { ...DEFAULT_SPECS }, sources: { softAt: "default", at: "default", buffer: "default" }, files: [], fromDefaults: true,
	};
	const paths: Array<[string, boolean]> = [
		[join(options.packageRoot, "config.json"), false],
		[join(options.agentDir, "self-compact", "config.json"), false],
		[flags.config ? resolve(options.cwd, flags.config) : join(options.cwd, ".pi", "self-compact", "config.json"), Boolean(flags.config)],
	];
	const seen = new Set<string>();
	for (const [path, required] of paths) {
		const absolute = resolve(path);
		if (seen.has(absolute)) continue;
		seen.add(absolute);
		const c = readConfig(absolute, required);
		if (!c) continue;
		result.files.push(absolute);
		if (c.notice !== undefined) { result.specs.softAt = String(c.notice); result.sources.softAt = "config"; }
		if (c.warning !== undefined) { result.specs.at = String(c.warning); result.sources.at = "config"; }
		if (c.compact !== undefined) { result.forcedAt = String(c.compact); result.sources.buffer = "config"; }
		if (c.buffer !== undefined) { result.forcedAt = undefined; result.specs.buffer = String(c.buffer); result.sources.buffer = "config"; }
		if (c.compactionPrompt !== undefined) result.compactionPrompt = c.compactionPrompt;
		if (c.noteInstructions !== undefined) result.noteInstructions = c.noteInstructions;
	}
	for (const key of ["softAt", "at", "buffer"] as const) {
		if (flags[key] !== undefined) {
			if (!flags[key]!.trim()) throw new Error(`Empty self-compact flag: ${key}`);
			result.specs[key] = flags[key]!;
			result.sources[key] = "flag";
			if (key === "buffer") result.forcedAt = undefined;
		}
	}
	if (flags.prompt !== undefined) {
		if (!flags.prompt.trim()) throw new Error("--compact-prompt must not be empty");
		result.compactionPrompt = flags.prompt;
	}
	validateSpecs(result.specs);
	result.fromDefaults = Object.values(result.sources).every(source => source === "default");
	return result;
}

/** A direct maximum is re-resolved against each selected model, including mixed units. */
export function resolveConfiguredThresholds(specs: ThresholdSpecs, forcedAt: string | undefined, window: number, fromDefaults = false): ResolveResult {
	if (forcedAt === undefined) return resolveThresholds(specs, window, { fromDefaults });
	if (!Number.isFinite(window) || window <= 0) return { ok: false, error: "Model context window is unknown; cannot resolve thresholds." };
	try {
		const preliminary = resolveThresholds({ ...specs, buffer: "0" }, window, { fromDefaults: false });
		if (!preliminary.ok) return preliminary;
		const target = parseTokenSpec(forcedAt, "compact");
		const warning = parseTokenSpec(specs.at, "warning");
		const toTokens = (s: ReturnType<typeof parseTokenSpec>) => s.kind === "percent" ? Math.floor(s.value / 100 * window) : s.value;
		const cutoff = toTokens(target), warn = toTokens(warning);
		if (cutoff > Math.floor(window * .9)) return { ok: false, error: `compact (${forcedAt}) exceeds the 90% cap of this model window.` };
		if (cutoff < warn) return { ok: false, error: `compact (${forcedAt}) must not be below warning (${specs.at}).` };
		return resolveThresholds({ ...specs, buffer: String(cutoff - warn) }, window, { fromDefaults: false });
	} catch (error) {
		return { ok: false, error: error instanceof Error ? error.message : String(error) };
	}
}
