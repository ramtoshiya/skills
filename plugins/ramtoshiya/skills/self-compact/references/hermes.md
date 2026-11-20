# Hermes in BB {:#bb-hermes}

Call `self_compact` with action `compact` and the complete handoff note as `note`. Add
`resume: false` when the next step needs the user's answer. The tool saves the note and starts the
helper from the BB section of SKILL.md for this thread. Do not run the helper or write the note
through the terminal.

- `"status": "scheduled"`: end the turn at once with one line saying compaction is scheduled and
  work will resume. With `resume: false`, end with the question instead. Call no other tool in
  that turn and send nothing to this thread.
- `"status": "error"`: the note is saved unless the error says otherwise. Keep working, and call
  `compact` again only at a later natural boundary. Hermes compresses on its own at its window.

BB reports a `/compact` that Hermes refused or found nothing to compact as finished too. So the
helper also requires the one manual compaction that Hermes committed for this thread after the
request. If compaction fails, a message starting with "Self-compaction did not complete" arrives
in this thread or with your next turn or tool result. It arrives once and the note stays. Do not
retry at once. Action `read` returns the note and the last helper's result.
