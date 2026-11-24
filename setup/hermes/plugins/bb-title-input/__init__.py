"""Add bb's `<system_instructions>` block to the control wrappers that Hermes's titler strips.

Hermes has no hook for the title input, so this appends to the private
`agent.title_generator._CONTROL_WRAPPERS`. If a Hermes update renames it, `register` raises
and the plugin fails to load.
"""

from __future__ import annotations

BB_BLOCK = ("<system_instructions>", "</system_instructions>")


def register(ctx) -> None:
    from agent import title_generator

    wrappers = title_generator._CONTROL_WRAPPERS
    if BB_BLOCK not in wrappers:
        title_generator._CONTROL_WRAPPERS = (*wrappers, BB_BLOCK)
