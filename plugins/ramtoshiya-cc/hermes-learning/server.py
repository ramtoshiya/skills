"""Stdio MCP server that serves Hermes's own memory, skill_manage and skill_view tools to Claude Code.

launch.py runs it under the Hermes interpreter with HERMES_HOME set to the learning store. Hermes's handlers
do their own validation, char limits, security scan, write-approval gate, ledger and .usage.json telemetry.
skill_manage and skill_view go through model_tools.handle_function_call, the dispatcher Hermes's agent uses.
memory is an agent-loop tool that handle_function_call refuses, so it goes through registry.dispatch with a
store freshly loaded from disk, as Hermes's /memory and gateway paths load it.

The session's bb thread decides its role: a child thread only reads skills and proposes lessons in its
final answer, a review fork writes with Hermes's background_review origin (review-only guards, created skills
marked agent-created for the curator), and any other session writes as foreground. A session of the Hermes
coder runtime, which learns through Hermes itself, gets no tools. The server still starts there, because
Claude Code would cache an exit as a failure and skip the server in every session for the next 15 minutes.
"""

import importlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store  # noqa: E402

SERVED = ("memory", "skill_manage", "skill_view")
REVIEW_PROMPT = Path(__file__).with_name("review.md")
RECORD = ("Hermes learning store: memory holds the USER.md and MEMORY.md notes shown at session start, and the "
          "skills are the hermes-skills plugin. Load these tools with ToolSearch before the first call. When this "
          "session confirms a lesson a later session would reuse, such as a user preference or correction, a fact "
          "about the machine or a project, or a procedure that worked, record it then: memory for a short fact, "
          "skill_manage for a procedure (skill_view the skill before you patch it). Record only what a person "
          "or an agent in the conversation stated, or a tool result showed.")
REVIEW_TITLE = "Hermes review"
FORK = (f" When the conversation as a whole is worth reviewing for lessons, for example after a long task with "
        f"several corrections, start a review fork instead of recording piece by piece: run "
        f"`bb thread fork \"$BB_THREAD_ID\" --lifecycle-owner-thread \"$BB_THREAD_ID\" --title \"{REVIEW_TITLE}\" "
        f"--prompt-file {REVIEW_PROMPT}` and go on with your work. The fork mails you its summary.")
CHILD = ("You are a child agent that another agent started. Read Hermes skills, but do not record memory or "
         "skills. End your final answer with a `Learning proposals` section of at most five bullets. Each "
         "bullet is something your own tool runs in this task showed that a later session could reuse, such "
         "as a command that works, a path, or a project rule, followed by the command or file that shows it. "
         "Write `Learning proposals: none` when nothing qualifies.")
REVIEW = "This thread is a learning review fork. Follow its first prompt."
ROLES = {
    "top": {"tools": SERVED, "origin": "foreground", "instructions": RECORD + FORK},
    "solo": {"tools": SERVED, "origin": "foreground", "instructions": RECORD},
    "review": {"tools": SERVED, "origin": "background_review", "instructions": REVIEW},
    "child": {"tools": ("skill_view",), "origin": "foreground", "instructions": CHILD},
    "off": {"tools": (), "origin": "foreground", "instructions": ""},
}
SKILL_PREFIX = "hermes-skills:"
AGENT_LOOP = {"memory"}
PROTOCOL_VERSION = "2025-06-18"


def protocol_stream():
    """Keep fd 1 for JSON-RPC only: Hermes code may print or log to stdout."""
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def role() -> str:
    if store.in_coder_runtime():
        return "off"
    thread_id = os.environ.get("BB_THREAD_ID")
    if not thread_id:
        return "solo"
    shown = subprocess.run([os.environ.get("BB_CLI", "bb"), "thread", "show", thread_id, "--json"],
                           capture_output=True, text=True, timeout=20)
    thread = json.loads(shown.stdout or "{}").get("thread") or {}
    if thread.get("parentThreadId"):
        return "child"
    is_review = thread.get("originKind") == "fork" and (thread.get("title") or "").startswith(REVIEW_TITLE)
    return "review" if is_review else "top"


def tool_list(served):
    """Schemas from the three tool modules alone, in about 0.3 s. Importing model_tools registers every Hermes
    tool and takes 5-25 s, longer than Claude Code waits for an MCP server, so tools/list does not wait for it."""
    import tools.memory_tool, tools.skill_manager_tool, tools.skills_tool  # noqa: E401,F401
    from tools.registry import registry
    listed = []
    for name in served:
        fn = registry.definition_for(name)["function"]
        listed.append({"name": name, "description": fn.get("description", ""),
                       "inputSchema": fn.get("parameters") or {"type": "object", "properties": {}}})
    return listed


def warm_up():
    """Import the dispatcher, then run the curator when its interval has passed. No Hermes agent runs for this
    store any more, so nothing else would."""
    importlib.import_module("model_tools")
    from agent.curator import maybe_run_curator
    maybe_run_curator()


def is_error(text):
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and (payload.get("success") is False or "error" in payload)


def call(name, args, session_id, served):
    if name not in served:
        return json.dumps({"success": False, "error": f"Unknown tool: {name}"}), True
    import model_tools
    from tools.registry import registry
    if str(args.get("name", "")).startswith(SKILL_PREFIX):
        args = {**args, "name": args["name"][len(SKILL_PREFIX):]}
    if name in AGENT_LOOP:
        from tools.memory_tool import load_on_disk_store
        result = registry.dispatch(name, args, store=load_on_disk_store(),
                                   task_id=session_id, session_id=session_id)
    else:
        result = model_tools.handle_function_call(
            name, args, task_id=session_id, session_id=session_id,
            enabled_toolsets=["memory", "skills"])
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return text, is_error(text)


def main():
    out = protocol_stream()
    current = ROLES[role()]
    listed = []
    if current["tools"]:
        listed = tool_list(current["tools"])
        # A tools/call imports model_tools too. The import lock makes it wait for this thread.
        threading.Thread(target=warm_up, daemon=True).start()
        from tools.skill_provenance import set_current_write_origin
        set_current_write_origin(current["origin"])
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("BB_THREAD_ID")

    def reply(msg_id, result=None, error=None):
        body = {"jsonrpc": "2.0", "id": msg_id}
        body.update({"error": error} if error else {"result": result})
        out.write(json.dumps(body, ensure_ascii=False) + "\n")

    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if msg_id is None:
            continue
        if method == "initialize":
            reply(msg_id, {"protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                           "capabilities": {"tools": {}},
                           "serverInfo": {"name": "hermes-learning", "version": "1"},
                           "instructions": current["instructions"]})
        elif method == "tools/list":
            reply(msg_id, {"tools": listed})
        elif method == "tools/call":
            text, failed = call(params.get("name"), params.get("arguments") or {}, session_id, current["tools"])
            reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": failed})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
