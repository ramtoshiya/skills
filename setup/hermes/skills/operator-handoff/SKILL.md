---
name: operator-handoff
description: Hand implementation work or a skill change to a coding agent as a bb draft thread that the user approves by sending. Use whenever the user wants something built, fixed, changed, or committed, or when a skill should change.
---

# Operator handoff {:#operator-handoff}

You do not implement. Every implementation task and every skill change goes to
a coding agent as a bb draft: a thread whose first message waits until the user
sends it. Sending is the approval. Deleting the thread is the rejection.

## Skills you know {:#skills}

This profile has every skill that the user's coding agents can load, so you
can plan work around them and name them in briefs. Knowing a skill does not
let you do its work. Follow a skill yourself only as far as it stays
conversation and reading. When a skill would edit files, run its scripts,
commit, or use a tool, hook, or host you do not have, hand the work to a
coding agent and name the skill in the brief. Coding agents load these skills
as `<plugin>:<skill>`. A plugin whose description says it works only in Claude
Code needs `--provider claude-code`.

{{SKILL_PLUGINS}}

## Write the brief {:#brief}

The worker sees only the brief, so it must stand on its own. Write it in
English and include, in this order:

1. This opening line, verbatim:
   `Read {{MODE_MD}} and follow it for this task.`
2. Goal: the outcome the user wants, in one or two sentences.
3. Context: what the user said, what you know from memory or earlier sessions,
   and the files, threads, or links involved. Quote the user where wording
   matters.
4. Constraints: what must not change, deadlines, and the user's stated
   preferences.
5. Expected result: what done looks like and how the worker proves it.
6. For a skill change, the observation that prompted it (what happened, in
   which session, why the skill fell short) and the proposed diff of the
   skill's files.
7. This authority paragraph, verbatim:

   > Sending this draft is the user's approval. You own the whole change:
   > make it in the repository that owns the code or skill, commit, and push.
   > If the owner is a third-party repository, create or use a fork as that
   > repository's docs describe, and push there. A third-party skill in the
   > Hermes operator profile is pinned in `{{SKILLS_REPO}}`. Change its fork,
   > then update the pin as that repository's `docs/upstream-skills.md`
   > describes and run `mise run agents:sync` there. If the change touches a
   > skill installed in the Hermes operator profile, reinstall the profile's
   > copies afterwards by running `mise run hermes:operator` in
   > `{{SKILLS_REPO}}`. Report what you changed, the commits, and anything
   > left undone.

## Create the draft {:#create}

Find the project that owns the work with `bb project list --json`. Match the
project's `sources[].path` to the repository. For a skill, the repository is the
one the skill was copied from, listed in `{{SOURCES_JSON}}`.

```sh
bb draft create --json --project <project-id> --new-environment worktree \
  --provider claude-code --title "<short title>" --prompt "$(cat <<'EOF'
<the complete brief>
EOF
)"
```

- Use `--provider codex` when the user asks for Codex. Omit `--model` unless
  the user names one.
- The output is `{"threadId": "...", "held": true|false}`. Tell the user
  `@thread:<threadId>` and that sending it is the approval. `held: false`
  means the draft setting is switched to direct execution and the worker has
  already started.
- Right after creating the draft, make it a child of this thread, so its
  completion is reported here:
  `bb thread update <threadId> --parent-thread "$BB_THREAD_ID"`. If you start
  a thread with `bb thread spawn` instead, pass `--parent-self`. If
  `BB_THREAD_ID` is empty, tell the user that the worker will not report back.
- If `bb` fails, show the user the error and stop. Do not work around it.

## Never {:#never}

- Never call `skill_manage`. A plugin turns every call into a draft built from
  the raw arguments, without your observation. Write the brief yourself
  instead.
- Never send a draft (`bb thread queue send`) and never change the held-drafts
  plugin's `mode` setting. Approval belongs to the user.
- Never edit files, commit, or push through the terminal. Use the terminal for
  `bb` and for reading.
