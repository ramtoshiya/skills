"""Name a bb session after the user's message, not after bb's instructions.

bb starts every thread's first message with a `<system_instructions>` block
(its plugin text, AGENTS.md, and the skill list) and puts the user's text after
the closing tag. Hermes titles a session from that message, so the title
described the instructions, such as "BB environment setup instructions #12",
and bb adopted it whenever its own title generation failed.

Hermes's titler already drops recognized control wrappers and titles the prose
after them. This plugin adds bb's block to that list. Only the titler reads the
list, so the message the model receives is unchanged.

Hermes offers no hook for the title input, so the plugin appends to
`agent.title_generator._CONTROL_WRAPPERS`. If a Hermes update renames it,
`register` raises and the plugin fails to load, and `npm test` fails against
the installed Hermes.
"""

from __future__ import annotations

BB_BLOCK = ("<system_instructions>", "</system_instructions>")


def register(ctx) -> None:
    from agent import title_generator

    wrappers = title_generator._CONTROL_WRAPPERS
    if BB_BLOCK not in wrappers:
        title_generator._CONTROL_WRAPPERS = (*wrappers, BB_BLOCK)
