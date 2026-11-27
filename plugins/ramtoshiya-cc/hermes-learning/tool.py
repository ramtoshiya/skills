"""Run one Hermes learning tool for cli.py. Runs under the Hermes interpreter with HERMES_HOME set to the store.

Usage: tool.py <tool> (JSON arguments on stdin), or tool.py schema <tool>
Hermes's handlers do their own validation, char limits, security scan, write-approval gate, ledger and
.usage.json telemetry. skill_manage and skill_view go through model_tools.handle_function_call, the dispatcher
Hermes's agent uses. memory is an agent-loop tool that handle_function_call refuses, so it goes through
registry.dispatch with a store freshly loaded from disk, as Hermes's /memory and gateway paths load it. It skips
model_tools, which loads every Hermes tool and takes about two seconds.
"""

import json
import os
import sys

SKILL_PREFIX = "hermes-skills:"


def schema(name):
    import tools.memory_tool, tools.skill_manager_tool, tools.skills_tool  # noqa: E401,F401
    from tools.registry import registry
    fn = registry.definition_for(name)["function"]
    return json.dumps({"name": name, "description": fn.get("description", ""),
                       "arguments": fn.get("parameters") or {}}, ensure_ascii=False, indent=1)


def call(name, args, session_id):
    """Claude Code lists the learned skills as hermes-skills:<name>, and agents pass that name on."""
    if str(args.get("name", "")).startswith(SKILL_PREFIX):
        args = {**args, "name": args["name"][len(SKILL_PREFIX):]}
    if name == "memory":
        from tools.memory_tool import load_on_disk_store
        from tools.registry import registry
        result = registry.dispatch(name, args, store=load_on_disk_store(), task_id=session_id, session_id=session_id)
    else:
        import model_tools
        result = model_tools.handle_function_call(name, args, task_id=session_id, session_id=session_id,
                                                  enabled_toolsets=["memory", "skills"])
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def failed(text):
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and (payload.get("success") is False or "error" in payload)


def main():
    args = sys.argv[1:]
    if args[0] == "schema":
        print(schema(args[1]))
        return
    try:
        arguments = json.loads(sys.stdin.read())
    except ValueError as bad:
        sys.exit(f"hermes-learning: the arguments on stdin are not JSON: {bad}")
    text = call(args[0], arguments, os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("BB_THREAD_ID"))
    print(text)
    sys.exit(1 if failed(text) else 0)


if __name__ == "__main__":
    main()
