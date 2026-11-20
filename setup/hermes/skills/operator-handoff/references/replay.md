# Replay experiments {:#replay}

A replay asks a past question again to compare models, harnesses, or
instructions. The later result is what happened after the original question.

1. Before the first run, list where the later result is visible from a new
   thread, including installed plugins, other threads and their storage,
   branches and worktrees of the same repository, and memory or session
   history. In the prompt, name the threads the run may read and the places
   it must not.
2. For a new design, start one run and read its log before starting the
   others. If a tool result shows the later result, change the design first.
3. Search every finished run's log for the later result's names and the
   forbidden places. Count what the run itself opened, not text quoted inside
   material it was allowed to read. Discard a run that saw the later result
   and report it as discarded.

When a comparison changes two factors at once, look for a route that holds
one fixed and run it before reporting that they cannot be separated. `claudex`
runs GPT models in Claude Code. A GPT model on `claudex` against a Claude
model on `claude-code` holds the harness nearly fixed. The same GPT model on
`codex` against `claudex` holds the model fixed. Report the settings added by
`claudex`, listed in `{{SKILLS_REPO}}/tools/claudex/README.md`, as remaining
harness differences.
