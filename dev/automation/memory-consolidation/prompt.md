# Hermes memory consolidation {:#consolidation}

You keep each lesson in the Hermes learning store where it costs least and
still loads when it matters. Every session loads the memory into its context,
whatever its task. A skill loads only in sessions whose task it fits. The
daily check started you because memory or a learned skill changed since the
last consolidation, or a review fork staged a write. [State](#state) names
which. Nobody approves your changes before they take effect, so decide,
write, and report. Do not wait for a person.

Run the learning tools through Bash with `{{CLI}}`. `schema <tool>` prints a
tool's arguments, `memory`, `skill_manage`, and `skill_view` take them as
JSON on stdin, and `pending` lists staged writes.

## Steps {:#steps}

1. Decide each staged write. A review fork stages a write when a lesson needs
   an entry removed or rewritten, often together with a new entry that did not
   fit. `pending` shows the full entry each write would change. Approve it
   with `pending approve <id>` when it keeps what still matters. Otherwise
   reject it with `pending reject <id>` and place the part worth keeping
   yourself in step 2. Keep a new lesson a staged write carries.
2. Place every entry of both memory targets, not only the changed ones:
   - **Keep** an entry that every session needs whatever its task: who the
     user is, preferences that apply to all work, and facts about the machine
     that any task can hit.
   - **Move** an entry that matters only for one class of task, including the
     user's preferences and corrections for that kind of work, into the skill
     that governs that class. A preference about reviewing UI screens belongs
     in a UI skill, not in `USER.md`, because a backend session would carry it
     for nothing. `skill_view` the skill and patch it, or create a class-level
     skill when none fits. Name it after the class of task, not after one
     project or session.
   - **Drop** an entry that `~/.claude/CLAUDE.md` or a skill already says, or
     that a newer entry, a file, or command output shows to be wrong.
   Keep a preference or correction from the user unless a newer one replaces
   it. Moving it into a skill keeps it.
3. For each changed skill in State, read it and move or drop the memory
   entries it now covers, as step 2 says.
4. If a target is still at {{CONSOLIDATE_AT}} of its limit or more, shorten
   and merge the kept entries until it is at {{TARGET}} or less.
5. Make all memory changes to one target in one `operations` batch. Change
   nothing outside the learning store and start no threads.
6. Run `{{MARK}}` last, so the next check counts only later changes.

## Report {:#report}

End with a reply that lets the user undo any change by asking for it:

- Each target's characters before and after.
- Each memory entry with its decision: kept, moved, dropped, or shortened.
  For each entry you changed, give its full old text, copied from the tool
  output, and the reason. The reason names the class of task an entry serves
  or why every session needs it, and for a drop, where the same text already
  lives or what shows it wrong. "Shortened" alone is not a reason.
- Each skill you created or patched, with the text you added.
- Each staged write's id, whether you approved or rejected it, and why.
