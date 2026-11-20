---
name: github-actions-authoring
description: >-
  Use before creating or editing .github/workflows/*.yml, .github/workflows/*.yaml,
  action.yml, or action.yaml anywhere in a repository, even for a small non-version
  change. Verify every remote uses dependency against its official GitHub releases,
  enforce a 72-hour release cooldown, inspect compatibility and security, and pin
  original-repository commit SHAs. Never choose action versions from model memory.
metadata:
  short-description: Verify GitHub Actions releases, compatibility, and immutable pins before editing
---

# GitHub Actions authoring {:#github-actions-authoring}

Workflow dependencies execute code, often with repository credentials. A familiar
major tag is not evidence that its current contents are compatible or safe. Never
choose action versions from model memory, copied workflows, or a stale version list.
Use the same evidence rules in any agent host. This skill is an authoring procedure,
not a hook that automatically blocks unsafe edits.

## Check tools before editing {:#required-tools}

Read the target repository's instructions and documented checks first. Find `gh`,
`git`, `actionlint`, `zizmor`, and its test runner on `PATH` with `command -v`.
If a required CLI is missing, name it and the repository's documented install/sync
step, then stop before editing. This skill never installs, updates, or builds a CLI.
Do not substitute a floating installer, global package install, or one-shot download.

For this pack, use the machine setup documented in `docs/setup.md` and the agent
installation/update steps in `docs/agent-pack.md`. In another repository, use its
own setup documentation. If no install/sync step is documented for a missing tool,
report that gap and stop instead of inventing a command.

Treat tool versions and advisories as dependencies too. Record installed versions,
verify their official releases and applicable advisories, and apply the same
72-hour cooldown and compatibility review when selecting a tool version. An exact
pin can still be vulnerable. Check repository security advisories and the GitHub
Advisory Database for the actions and tools being used. A known-vulnerable release
is not an acceptable fallback just because a fix is still inside the cooldown.

Never enable verbose/debug `zizmor` logging while a GitHub token is present. Run
ordinary audits without tokens, including `GH_TOKEN` and `GITHUB_TOKEN`, and
without debug environment settings such as `RUST_LOG=debug` or `RUST_LOG=trace`.
Check for other token sources/configuration too. Only supply a least-privilege
token if an online audit strictly requires it, with normal logging and no shell
tracing. Never print credentials or include them in evidence or command logs.

## Inventory dependencies {:#dependency-inventory}

Read [dependency inventory](references/dependency-inventory.md) to enumerate every dependency, including local, nested, and Docker sources.

## Select a release from current evidence {:#release-selection}

Read [release selection](references/release-selection.md) to verify official releases, the 72-hour cooldown, and eligibility.

## Resolve provenance and inspect compatibility {:#provenance-and-compatibility}

Read [provenance and compatibility](references/provenance-and-compatibility.md) to resolve original-repository SHAs and inspect each caller.

## Edit and validate {:#edit-and-validation}

Only edit after all dependency evidence and compatibility decisions are complete.
Pin each remote GitHub `uses:` to the verified full commit SHA, retaining its
original repository and subpath, and add a human-readable version comment with the
exact release tag. Never guess a SHA or leave a mutable tag or branch in final
workflow changes. Keep the tag only in the comment. Do not treat an existing full
SHA as a substitute for checking the newest eligible release.

After workflow edits, require all of the following:

- `actionlint` for syntax, schema, expressions, and workflow contracts. Its slower
  release cadence is not evidence of action currentness or security. It does not
  validate standalone action metadata, so also check action files against their
  metadata schema and any documented action tests.
- `zizmor` for Actions security, with token-safe normal logging. Run the repository's
  documented command, or a local audit such as
  `env -u GH_TOKEN -u GITHUB_TOKEN -u RUST_LOG zizmor --offline .` after checking
  other token sources. Do not hide findings or disable rules to make checks pass.
- Repository tests and any other checks its instructions require. Review the final
  diff for immutable refs, explicit security-sensitive defaults, and behavior changes.
- An affected workflow run when feasible. Prefer the ordinary PR-triggered run.
  Manual dispatch needs the user's authorization, especially for write/deploy jobs.
  Do not run untrusted PR code with secrets. If no safe run is possible, state why
  and which behavior remains unverified. Report pending CI without claiming success.

Do not claim validation passed when a required CLI is missing, an audit fails, or
a workflow has not run. Stop on missing local prerequisites or failed checks and
report the exact failure. Distinguish local checks from remote execution results.

## Delivery evidence {:#delivery-evidence}

When reporting results, read [delivery evidence](references/delivery-evidence.md).
