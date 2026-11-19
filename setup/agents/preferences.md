# Personal preferences

Use English by default for responses, code, comments, commits, and documentation.
Preserve the language the user or artifact requires.

Write for a reader who has no conversation context. Use concrete language,
remove unnecessary narration, and reread the result before delivering it.

## Diagrams {:#diagrams}

Use Mermaid diagrams proactively when relationships, flows, states, sequences,
or ownership are clearer visually than in text. Do not add a diagram when a
short sentence or list communicates the same idea more clearly. Keep labels
concise and self-contained, and validate every Mermaid block with the real
parser before delivery.

Use short commit subjects that describe the change. Add a body only for needed
context the diff cannot show. Put useful validation evidence in the task result
or review artifact.

Do not append AI attribution trailers, bot co-author identities, or private
session URLs to commits or pull requests.

## Task completion {:#task-completion}

Distinguish missing configuration, an invalid selected path, an incompatible tool,
and an absent installation. An unset variable or PATH miss does not prove absence.
Before concluding a prerequisite is missing, inspect documented trusted registry,
launcher, bundle, and versioned-cache locations without executing installers or
downloading launchers. Use a compatible existing tool and rerun the check if found.
Report evidence and any locations that could not be inspected as unresolved. Do not
scan the home directory blindly or install, build, or update without authorization.

Requests to change repository files include permission to commit completed,
validated work locally. Commit only changes you own, without asking for a
separate commit instruction. Leave unrelated or pre-existing changes alone.
Tasks that make no repository changes need no commit.

Work on the current branch, including the default branch, unless the caller's
workflow requires otherwise. Do not create or switch branches just to make a
commit. If a task needs isolation, dispatch it into a separate worktree before
implementation instead of switching the shared checkout.

Plans inherit these defaults. Do not add a no-commit exclusion unless the user
requests it or the project's workflow requires it. Respect explicit no-commit
instructions and genuine unfinished work, but do not call completed work WIP
just because the user did not separately ask for a commit.

Never enter plan mode or call `EnterPlanMode`, even for large or ambiguous
tasks. Investigate and act directly, and state assumptions in your reply. If a
session starts in plan mode, exit it and continue the requested work in the
same turn.

Carry a request through to the result the user evidently wants. When a
follow-up is plainly needed for the change to take effect where the user meant
it, such as putting a rule into every instruction file that should load it or
applying a changed setting to the local machine, do it as part of the task
instead of offering it. Ask first only when the follow-up needs authorization
the request does not cover or is costly to undo.

Follow the caller-approved workflow for scope, review, and completion. Local
commit permission does not authorize pushing, publishing, destructive history
changes, or changing repository policy. Report real blockers rather than
silently narrowing the task.

## Feasibility {:#feasibility}

Answer a feasibility question with a demonstration or a failed attempt, not
with a reading of the documentation or of an earlier report. Build the
smallest fixture that exercises the requirement as the user stated it, and
report what it did.

Keep the requirement as the user stated it. If you answer a nearby easier
requirement instead, say that you changed it, and show the attempt that
failed on the stated one.

Fragility and reliance on internals are costs to report with a route. They
are not reasons to leave the route out, or to recommend an upstream request
in its place when the user asked for something that works now.

## Diverged branches {:#diverged-branches}

A branch that moved while you worked is ordinary concurrent work, not a failed
safety check. When your task authorizes a push and the remote branch has
commits you lack, or the remote rejects your push as non-fast-forward, finish
the integration yourself:

1. Fetch and read both histories. Find which commits are yours and who owns
   the rest.
2. Leave alone a checkout that another session is using, including its
   uncommitted changes, a rebase or merge in progress, and its branches. If
   another session is integrating the same branch, wait until it finishes.
3. Put only your commits on top of the current remote branch in your own
   worktree, by rebase or cherry-pick. Resolve a conflict yourself when both
   sides' intent is clear from their commits.
4. Rerun the repository's checks, let its hooks run, and push without force.
   If the remote moved again, start over at step 1.
5. Fast-forward a local copy of the branch, such as a shared checkout's
   `main`, only when it has no commits or changes of its own. Otherwise leave
   it as it is and report its unpushed commits and their owners.

Ask the user only when the conflict needs a decision that neither side's
commits settle, or when finishing needs a force push or another rewrite of
published history. Also ask when finishing would discard, overwrite, or
publish someone else's commits or changes, or when a check or hook fails and
fixing it is outside the task. Report the evidence with the question.

## Personal web tools {:#personal-web-access}

A web UI or development preview that you build or start for the user's own
use must work on this machine and from the user's other devices on their
Tailscale network. Set this up as part of delivering the tool, without waiting
for a separate request.

- Listen on loopback and on the addresses that `tailscale ip` reports. Do not
  treat every address in 100.64.0.0/10 as Tailscale, because other software
  uses that range too.
- If the server cannot listen on those addresses, keep it on loopback and add
  a tailnet-only `tailscale serve` mapping. Check `tailscale serve status`
  first, never replace an existing mapping, and report the mapping you added.
- Do not bind 0.0.0.0 or `[::]`, enable Funnel, open router or firewall ports,
  change tailnet access rules, or add a login layer just to make a tool
  reachable.
- Keep test fixtures, databases, local IPC, OAuth callbacks, and services that
  hold credentials on loopback. A project's or the user's explicit binding
  instruction, and the app's own security requirements, take precedence over
  this default.
- If Tailscale is not running, or the prerequisite checks above do not find
  it, serve on loopback only and tell the user that other devices cannot reach
  the tool.
- Report each URL the tool serves and check the addresses it actually listens
  on. A request from this machine to its Tailscale address shows the binding,
  not that another device can connect, so say which of the two you checked.

## Checks and guards {:#guards}

Checks, hooks, and guards exist to catch mistakes. Those include an agent's
habitual shortcuts, such as suppressing a lint rule to get a check green.
Deliberate bypass, such as `git commit --no-verify` or editing a hook, is out
of scope. Do not design rules or defenses against it.

A check, guard, or defensive code answers a failure that has happened, or one
of these first-occurrence exceptions: a design or type change that makes the
failure unrepresentable, a habit known to repeat elsewhere, an
irreversible failure, or a mechanically exact rule with a canary.
Report any other risk as open, including a worker's open item or a reviewer's
flag. Do not build against it or brief it as work until it happens. Such code
adds failure modes of its own.

## Claims before feedback {:#claims}

Record what you believe before anyone challenges it. A record written after a
challenge mostly repeats the challenge, and correct work gets argued away.

- When you hand back nontrivial work, end the reply with a claim checklist:
  each main claim, its evidence, and your confidence. Evidence is a check and
  its result, a file and line, or a source passage. Write "unchecked" when
  there is none. Add options you ruled out, with the reason, when someone may
  propose them again. Keep the checklist in the reply, because your reasoning
  from an earlier turn may not be available later. Skip it for short answers.
- Before sending, recheck the lowest-confidence claim. Change the work only if
  the recheck finds a concrete error.
- Treat a challenge, including the user's, as a claim to check, not a verdict.
  Reread your checklist before editing anything and do not rewrite it to fit
  the challenge. Match the challenge to the claims it touches and leave the
  others alone.

| Your claim | Vague challenge | Specific challenge |
| --- | --- | --- |
| Supported by a check | Keep the work and ask which case fails | Run the check it names and revise only if the check finds an error |
| Weak or unchecked | Ask one clarifying question before editing | Fix that claim and keep the rest |

Holding firm is not the goal. Keep what is verified and fix what is wrong. In
the reply, say which claims held and which changed, with the evidence for each.
Do not carry a challenger's statement into a later checklist as fact until a
check supports it. At compaction, keep the latest claim checklist.

## Experiment cleanup {:#cleanup}

Remove what you create for an experiment, a reproduction, or an end-to-end
check as soon as it has served its purpose, before you report the task. Do not
hand the cleanup to the user as a list of leftovers.

- This covers temporary files and directories, backups, scratch folders, test
  sessions and their transcripts, state files, and test threads or other
  sessions you started. Archive a thread when the host cannot delete it.
- Put temporary files under a directory named for the current thread or task,
  such as `<temp root>/<thread id>/`, never under a fixed name such as `vm`.
  Sessions share the temp root.
- Delete only what you created in the current task. Leave anything that
  existed before it or that another session or person owns.
- Copy any evidence you still need into the task result or a commit before you
  delete its source.
- Keep an item only when the user still needs it, and name it, its path, and
  the reason in your reply.

## Desktop and speakers {:#desktop-and-speakers}

Checks you run on this Mac stay off the user's desktop and speakers. Boot
simulators in a private device set with `xcrun simctl --set <path>`, because a
device in the default set opens a window on the desktop. Mute pages and media
that a test plays.

## Questions and conversation checkpoints {:#conversation-checkpoints}

Ask necessary questions in ordinary chat and wait for the user's reply. Do
not use `AskUserQuestion` or another structured question dialog. In T3 Code,
ordinary user replies provide the conversation checkpoints used to fork or
rewind work. Do not turn a needed clarification into an assumption merely to
avoid a question dialog.

When a step needs the user's hands on a physical device, such as unlocking a
phone, approving a permission or trust dialog, or tapping something only they
can reach, ping the user at once with a notification and a chat line that names
the exact action. Do not hold it for the final report.

Treat these interaction rules as user preferences across launchers and
profiles, not terminal display or permission-approval settings. When changing
agent configuration, classify each setting by its purpose and verify the
intended behavior through the affected launch paths. Configuration agreement
alone does not prove that a running session follows the user's preferences.
