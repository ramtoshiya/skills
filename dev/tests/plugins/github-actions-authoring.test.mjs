import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const skill = new URL("../../../plugins/ramtoshiya/skills/github-actions-authoring/SKILL.md", import.meta.url);

const contracts = [
	["discovers workflow and action edits", [
		"Use before creating or editing .github/workflows/*.yml, .github/workflows/*.yaml, action.yml, or action.yaml anywhere in a repository, even for a small non-version change.",
	]],
	["inventories remote dependencies before editing", [
		"Enumerate every remote `uses:` dependency before editing, including unchanged steps in affected files, planned additions, job-level reusable workflows, and remote dependencies nested in composite actions or reusable workflows you inspect.",
		"`docker://` images need verified publisher provenance, stable release age, and an immutable image digest.",
	]],
	["requires current official release evidence", [
		"Never choose action versions from model memory, copied workflows, or a stale version list.",
		"Establish the action's official GitHub repository from its publisher's documentation and repository identity.",
		"gh api --paginate \"repos/$repo/releases?per_page=100\"",
		"Choose the newest compatible stable release among those that qualify.",
		"Review release notes and migration guidance for the selected release and intervening releases since the existing pin.",
	]],
	["enforces the publication cooldown and excludes unstable releases", [
		"A qualifying release has `draft == false`, `prerelease == false`, a stable version, and a verified `published_at` at least 72 hours before that lookup time:",
		"lookup_time_utc - published_at_utc >= 259200 seconds",
		"Exclude future or missing publication timestamps and versions labeled alpha, beta, rc, nightly, or otherwise unstable even if incorrectly marked stable.",
		"Do not waive, bypass, or shorten the cooldown, even for urgency or a security fix.",
	]],
	["requires compatibility and security review", [
		"Read `action.yml` or `action.yaml` at that SHA, under the exact action subpath if present, plus the selected release notes and relevant official documentation.",
		"`runs.using`, its runtime support, minimum runner version, runner OS/architecture, and any self-hosted runner requirements.",
		"Breaking changes and changed defaults, including inputs, outputs, environment requirements, event behavior, and reusable workflow interfaces.",
		"Token permissions, credentials, secret exposure, and trust boundaries on fork pull requests or `pull_request_target`.",
		"For checkout, explicitly set `persist-credentials: false` unless a documented job requirement needs persisted credentials.",
		"Cache behavior, cache keys, restored untrusted content, and automatic caching.",
	]],
	["pins the original repository commit", [
		"Resolve the selected release tag in the original repository to a full 40-character commit SHA.",
		"gh api \"repos/$repo/git/ref/tags/$encoded_tag\"",
		"For annotated tags, follow `object.type == \"tag\"` through `repos/$repo/git/tags/<object.sha>` until the object is a commit.",
		"Pin each remote GitHub `uses:` to the verified full commit SHA, retaining its original repository and subpath, and add a human-readable version comment with the exact release tag.",
		"Never guess a SHA or leave a mutable tag or branch in final workflow changes.",
	]],
	["fails closed when evidence or required tools are missing", [
		"If official lookup, tag provenance, or release age cannot be verified, stop before editing and report the missing evidence.",
		"Find `gh`, `git`, `actionlint`, `zizmor`, and its test runner on `PATH` with `command -v`.",
		"If a required CLI is missing, name it and the repository's documented install/sync step, then stop before editing.",
		"This skill never installs, updates, or builds a CLI.",
	]],
	["requires validation and protects authenticated logging", [
		"`actionlint` for syntax, schema, expressions, and workflow contracts.",
		"`zizmor` for Actions security, with token-safe normal logging.",
		"Repository tests and any other checks its instructions require.",
		"An affected workflow run when feasible.",
		"Treat tool versions and advisories as dependencies too.",
		"Never enable verbose/debug `zizmor` logging while a GitHub token is present.",
		"Run ordinary audits without tokens, including `GH_TOKEN` and `GITHUB_TOKEN`, and without debug environment settings such as `RUST_LOG=debug` or `RUST_LOG=trace`.",
	]],
];

for (const [name, instructions] of contracts) {
	test(`GitHub Actions authoring policy ${name}`, () => {
		const text = readFileSync(skill, "utf8");
		const source = (name.startsWith("discovers") ? text.split("---")[1] : text).replace(/\s+/g, " ");
		for (const instruction of instructions) {
			assert.ok(source.includes(instruction), `Missing policy instruction: ${instruction}`);
		}
	});
}
