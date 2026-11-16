#!/usr/bin/env python3
"""PostToolUse hint: a missing Python module means rerun with uv, not give up."""
import json
import re
import sys

MISSING = re.compile(r"ModuleNotFoundError: No module named '([A-Za-z0-9_]+)")


def hint(tool_response):
    text = tool_response if isinstance(tool_response, str) else json.dumps(tool_response, ensure_ascii=False)
    modules = sorted(set(MISSING.findall(text)))
    if not modules:
        return None
    names = ", ".join(f"`{module}`" for module in modules)
    return (
        f"Python could not import {names}. The tool can still run: rerun the same command as "
        "`uv run --with PACKAGE==VERSION python SCRIPT ARGS`, with one `--with` per missing "
        "package. PACKAGE is the distribution that provides the module and its name can differ, "
        "for example `pyyaml` provides `yaml`. Pin an exact version released at least three days "
        "ago, and add `--offline` to use only versions already in uv's cache. Do not install into "
        "the system Python."
    )


def main():
    try:
        context = hint(json.load(sys.stdin).get("tool_response"))
    except (ValueError, AttributeError, TypeError):
        return
    if context:
        json.dump({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}, sys.stdout)


if __name__ == "__main__":
    main()
