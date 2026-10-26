import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const skill = new URL("../plugins/ramtoshiya/skills/github-actions-authoring/SKILL.md", import.meta.url);

// The instructions are the shipped safety contract, not executable enforcement.
// Guard each independent failure mode without fixing paragraph order or wording.
const contracts = [
	["discovers workflow and action edits", [
		/\.github\/workflows\/\*\.yml/,
		/\.github\/workflows\/\*\.yaml/,
		/action\.yml/,
		/action\.yaml/,
		/before (?:creating|editing)/i,
	]],
	["inventories remote dependencies before editing", [
		/enumerate every remote `uses:` dependency before editing/i,
		/reusable workflows/i,
		/composite actions/i,
		/docker:\/\//,
	]],
	["requires current official release evidence instead of model memory", [
		/never (?:choose|select).*model memory/i,
		/official (?:GitHub )?repository/i,
		/releases\?per_page=100/,
		/--paginate/,
		/newest compatible stable release/i,
		/release notes/i,
	]],
	["enforces the publication cooldown and excludes unstable releases", [
		/published_at/,
		/draft.*false/i,
		/prerelease.*false/i,
		/72 hours/,
		/lookup_time_utc - published_at_utc >= 259200 seconds/,
		/exclude future or missing publication timestamps/i,
		/do not.*(?:waive|bypass|shorten).*cooldown/i,
	]],
	["requires compatibility review at the selected revision", [
		/runs\.using/,
		/minimum runner/,
		/breaking changes/,
		/changed defaults/,
		/permissions/,
		/credentials/,
		/cache behavior/,
		/action\.ya?ml.*(?:SHA|sha)/,
	]],
	["pins the original repository commit rather than a mutable ref", [
		/full 40-character commit SHA/,
		/original repository/,
		/annotated tags.*object\.type == "tag".*git\/tags\/<object\.sha>.*until the object is a commit/,
		/git\/ref\/tags/,
		/human-readable version comment/,
		/never.*mutable tag/i,
	]],
	["fails closed when evidence or required tools are missing", [
		/(?:cannot|cannot be).*verif[\s\S]{0,180}stop/i,
		/tag provenance/,
		/release age/,
		/command -v/,
		/install\/sync step/,
		/never installs, updates, or builds a CLI/i,
	]],
	["requires distinct validation and protects authenticated logging", [
		/actionlint/,
		/zizmor/,
		/repository tests/,
		/affected workflow run/,
		/tool versions and advisories.*dependencies/i,
		/never enable verbose\/debug.*GitHub token/i,
		/GH_TOKEN/,
		/GITHUB_TOKEN/,
	]],
];

for (const [name, patterns] of contracts) {
	test(`GitHub Actions authoring policy ${name}`, () => {
		const text = readFileSync(skill, "utf8");
		const source = (name.startsWith("discovers") ? text.split("---")[1] : text).replace(/\s+/g, " ");
		for (const pattern of patterns) {
			assert.ok(new RegExp(pattern.source, "i").test(source), `Missing policy instruction: ${pattern}`);
		}
	});
}
