def on_pre_llm_call(**_):
    return {"context": (
        "[pstack-mode turn check] Before you answer, check the principle index in operator-mode against this turn. "
        "For each principle whose trigger fits, read its leaf (skill_view principle-<title>, or its inlined text when present) "
        "and apply it. In the reply, name each principle that shaped a decision and the choice it changed."
    )}


def register(ctx):
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
