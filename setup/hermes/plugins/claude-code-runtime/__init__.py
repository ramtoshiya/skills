from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from agent import background_review
from agent.acp_openai_bridge import (completion_to_stream_chunks, extract_tool_calls_from_text,
                                     render_tool_bridge_sections)
from agent.runtime_cwd import resolve_agent_cwd
from hermes_cli.config import load_config_readonly
from hermes_cli.plugins_session_env import resolve_session_env
from hermes_constants import get_hermes_home
from providers import register_provider
from providers.base import ProviderProfile

NAME = "claude-code-runtime"
logger = logging.getLogger(__name__)
CLAUDE_MODELS = ("sonnet", "haiku", "opus", "fable")
GPT_MODEL = re.compile(r"^gpt-\d+(?:\.\d+)?-(?:astra|sol|terra|luna)$")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
REVIEW_PROMPTS = (background_review._MEMORY_REVIEW_PROMPT, background_review._SKILL_REVIEW_PROMPT,
                  background_review._COMBINED_REVIEW_PROMPT)
REVIEW_TOOLS = ("memory", "skill_manage", "skill_view", "skills_list", "read_file", "search_files")
FORK_NOTE = ("You are running as a forked copy of the coding session above, for a Hermes background review. "
             "The Hermes tools listed above are the only way to save memory or skills. They are not Claude Code "
             "tools, so ToolSearch and your own tool calls cannot reach them. To call one, write its "
             "<tool_call> block as plain text in your reply. Hermes runs it and sends you the result. Do not "
             "use your own Claude Code tools in this review and do not change any repository file. A child "
             "coder's answer in this conversation ends with learning proposals. Save a proposal only after a tool "
             "result in this conversation, or a file you read now with read_file or search_files, confirms it. "
             "search_files cuts long lines short, so read the whole file with read_file before you reject a "
             "proposal as contradicted. Leave out a proposal you cannot confirm, and name it with the reason in your "
             "final summary.")
# A hook, unlike a tool or permission rule, leaves the request prefix alone, so the fork still reads the
# coding run's cache.
REVIEW_SETTINGS = json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": (
    "echo 'Hermes background review: Claude Code tools are off. Call a Hermes tool by writing its "
    "<tool_call> block as plain text in your reply.' >&2; exit 2")}]}]}})
INVALID_CALL_NOTE = ("Your <tool_call> block was not valid JSON, so Hermes did not run it. Write the call again as "
                     "one <tool_call> block that holds one valid JSON object.")
RESULTS_NOTE = ("Continue the review. Call more Hermes tools in the same format, or reply with a short final "
                "summary and no tool call.")
GATEWAY_ONLY = re.compile(r"^(HERMES_|BB_THREAD_ID$|BB_PROJECT_ID$|BB_ENVIRONMENT_ID$|BB_THREAD_STORAGE$|PYTHONPATH$)")
EXTRA_BODY_KEY = "claude_code_runtime"
CODER_GUARD = Path(__file__).with_name("coder_guard.py")
CHILD_OUTPUT = re.compile(r"\bthread\s+output\b")
REFINE = ("/refine [Automatic, sent by Hermes Coder after it read a child coder's answer] Check the child coder's "
          "learning proposals in this session and save the ones a tool result confirms.")
MODE_NOTE = """## Working mode

Read `{root}/mode.md` and `{root}/HOSTS.md` before work, and again after compaction. Follow this mode for the whole \
session. You are a Claude Code coding session that a Hermes coder profile runs, so the Claude Code rules in HOSTS.md \
apply to you and its Hermes operator section does not."""
TURN_CHECK = ("[pstack-mode turn check] Make this your first step, before any other tool call: check the principle "
              "index in {root}/mode.md against this turn and read the leaf of each principle whose trigger fits. "
              "Apply them. In the reply, name each principle that shaped a decision and the choice it changed.")
SUBAGENTS_NOTE = """## Subagents

Claude Code's Agent tool is off in this session. When the task needs a subagent, start a child coder as a bb thread, \
and wait for it in the same turn:

```sh
bb thread show "$BB_THREAD_ID" --json   # thread.projectId and environment.id
bb nest spawn --provider {provider} --model claude-code-runtime:<model> --reasoning-level <effort> \\
  --parent-notifications off --project <project id> --environment <environment id> --title <role> \\
  --prompt-file <brief file>
bb thread wait <child id> --timeout 600 && bb thread output <child id>
```

- Every worker that the mode or a workflow asks for is such a child coder. `--provider {provider}` replaces the \
provider that ramtoshiya:worker-routing and its BB workers reference name.
- Choose the model and effort by the rows of the ramtoshiya:worker-routing skill, and pass both on every spawn: `sonnet` \
`high` for implementation and reads that need interpretation, and `opus` `high` for top-tier work. On a GPT route, the \
model is the output of `newest-model <family> claudex`, or the Claude row when that exits 1. Never pass an Astra model.
- A notice from the child would start a new turn right after this one and cancel Hermes's review of this session, so \
a hook refuses a spawn without `--parent-notifications off`. Run the wait again when it exits 2 (timeout). Exit 4 \
means the child failed: read it with `bb thread log <child id>`.
- A child coder reads this profile's skills and memory but saves neither. Its answer ends with learning proposals. \
Hermes's review of this session decides which of them to keep, so leave them in the conversation."""
CHILD_NOTE = """## You are a child coder

A parent coder started this session as a subagent. Use this profile's skills and memory, but do not change them: \
Hermes runs no review of this session, and a hook refuses writes to the profile's skills and memories directories.

End your final answer with a `Learning proposals` section of at most five bullets. Each bullet is something your own \
tool runs in this task showed that a later session could reuse, such as a command that works, a path, or a project \
rule, followed by the command or file that shows it. Write `Learning proposals: none` when nothing qualifies."""

_STATE_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()


@dataclass
class Fork:
    session: str
    sent: int


ForkKey = tuple[str, int, str]
_FORKS: dict[ForkKey, Fork] = {}


def command_for(model: str) -> str:
    return "claudex" if model.startswith("gpt-") else "claude"


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part["text"] for part in content
                         if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def review_index(messages: list[dict]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "user" and text_of(message.get("content")).startswith(REVIEW_PROMPTS):
            return index
    return None


def purpose_of(messages: list[dict], tools) -> str:
    if review_index(messages) is not None:
        return "review"
    if not tools:
        system = " ".join(text_of(m.get("content")) for m in messages if m.get("role") == "system").lower()
        return "title" if "title" in system else "aux"
    return "coding"


def effort_of(reasoning_config) -> str | None:
    if not isinstance(reasoning_config, dict) or reasoning_config.get("enabled") is False:
        return None
    effort = str(reasoning_config.get("effort") or "").lower()
    return {"minimal": "low"}.get(effort, effort) if effort in (*EFFORTS, "minimal") else None


def runtime_dir() -> Path:
    return Path(get_hermes_home()) / NAME


@dataclass(frozen=True)
class Role:
    learner_home: Path
    subagent_provider: str | None
    pstack_root: str | None

    @property
    def child(self) -> bool:
        return self.learner_home != Path(get_hermes_home())


def role() -> Role:
    section = load_config_readonly().get(EXTRA_BODY_KEY) or {}
    learner = section.get("learner_home")
    return Role(Path(learner) if learner else Path(get_hermes_home()), section.get("subagent_provider"),
                section.get("pstack_root"))


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def transcript_exists(session: str) -> bool:
    return any((claude_dir() / "projects").glob(f"*/{session}.jsonl"))


def usage_totals(result: dict) -> dict:
    usage = result.get("usage") or {}
    return {"fresh_input": int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or 0),
            "output": int(usage.get("output_tokens") or 0)}


@dataclass(frozen=True)
class LastCallPrompt:
    tokens: int
    cache_read: int


def last_call_prompt(events: list[dict]) -> LastCallPrompt | None:
    usages = [(event.get("message") or {}).get("usage") for event in events if event.get("type") == "assistant"]
    usage = next((u for u in reversed(usages) if u), None)
    if usage is None:
        return None
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    return LastCallPrompt(int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
                          + cache_read, cache_read)


def windows_path() -> Path:
    return runtime_dir() / "context-windows.json"


def known_windows() -> dict[str, int]:
    path = windows_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def record_window(model: str, events: list[dict], result: dict) -> None:
    started = next((e.get("model") for e in events if e.get("subtype") == "init"), None)
    window = ((result.get("modelUsage") or {}).get(started) or {}).get("contextWindow")
    if type(window) is not int or window <= 0:
        return
    with _STATE_LOCK:
        windows = known_windows()
        if windows.get(model) == window:
            return
        windows[model] = window
        path = windows_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".tmp").write_text(json.dumps(windows, indent=1), encoding="utf-8")
        path.with_suffix(".tmp").replace(path)


def log_usage(row: dict) -> None:
    path = runtime_dir() / "usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK, open(path, "a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")


def session_context(current: Role) -> str:
    notes = [MODE_NOTE.format(root=current.pstack_root)] if current.pstack_root else []
    notes += [SUBAGENTS_NOTE.format(provider=current.subagent_provider)] if current.subagent_provider else []
    notes += [CHILD_NOTE] if current.child else []
    memory = memory_context(current.learner_home)
    return "\n\n".join([f"# Hermes coder session\n\n" + "\n\n".join(notes)] * bool(notes) + [memory] * bool(memory))


def memory_context(learner_home: Path) -> str:
    memories = learner_home / "memories"
    parts = []
    for name, label in (("USER.md", "User profile"), ("MEMORY.md", "Environment memory")):
        path = memories / name
        text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        if text:
            parts.append(f"## Hermes {label} ({name})\n\n{text}")
    if not parts:
        return ""
    return ("# Hermes profile memory\n\nThis Claude Code session runs inside a Hermes session. These notes are "
            "the snapshot Hermes held when the session started.\n\n" + "\n\n".join(parts))


def learned_skills(learner_home: Path) -> dict[str, Path]:
    root = learner_home / "skills"
    manifest = root / ".bundled_manifest"
    bundled = ({line.split(":", 1)[0] for line in manifest.read_text(encoding="utf-8").split()}
               if manifest.is_file() else set())
    found = {}
    for skill_md in sorted(root.rglob("SKILL.md")) if root.is_dir() else ():
        parts = skill_md.relative_to(root).parts
        if not any(part.startswith(".") for part in parts) and skill_md.parent.name not in bundled:
            found[skill_md.parent.name] = skill_md.parent
    return found


def sync_skills_plugin(learner_home: Path) -> Path:
    root = runtime_dir() / "skills-plugin"
    skills = root / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    manifest = root / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        manifest.parent.mkdir(exist_ok=True)
        manifest.write_text(json.dumps({"name": "hermes-skills",
                                        "description": "Skills the Hermes profile learned"}) + "\n")
    wanted = learned_skills(learner_home)
    for link in skills.iterdir():
        if link.name not in wanted or not link.is_symlink() or Path(os.readlink(link)) != wanted[link.name]:
            link.unlink()
    for name, target in wanted.items():
        if not (skills / name).is_symlink():
            (skills / name).symlink_to(target, target_is_directory=True)
    return root


def conversation(key: str, cwd: str, current: Role) -> dict:
    path = runtime_dir() / "sessions.json"
    with _STATE_LOCK:
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        entry = state.get(key)
        if entry is None:
            session = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hermes:{get_hermes_home()}:{key}"))
            context = session_context(current)
            context_file = None
            if context:
                context_file = runtime_dir() / "context" / f"{session}.md"
                context_file.parent.mkdir(parents=True, exist_ok=True)
                context_file.write_text(context, encoding="utf-8")
            entry = state[key] = {"session": session, "cwd": cwd,
                                  "context": str(context_file) if context_file else None}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".tmp").write_text(json.dumps(state, indent=1), encoding="utf-8")
            path.with_suffix(".tmp").replace(path)
    return entry


def cache_prefix_flags(entry: dict, model: str, effort: str | None, plugin_dir: Path) -> list[str]:
    flags = ["--model", model]
    if effort:
        flags += ["--effort", effort]
    if entry["context"]:
        flags += ["--append-system-prompt-file", entry["context"]]
    return flags + ["--plugin-dir", str(plugin_dir), "--disallowedTools", "Agent"]


def guard_settings(current: Role) -> str:
    learner = [str(current.learner_home)] if current.child else []
    command = shlex.join([sys.executable, str(CODER_GUARD), current.subagent_provider or "", *learner])
    hooks = {"PreToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                             "hooks": [{"type": "command", "command": command}]}]}
    if current.pstack_root:
        check = shlex.join(["printf", "%s\n", TURN_CHECK.format(root=current.pstack_root)])
        hooks["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": check}]}]
    return json.dumps({"hooks": hooks})


def completion(text: str, model: str, totals: dict, tool_calls=None, context: LastCallPrompt | None = None,
               **extra) -> SimpleNamespace:
    message = SimpleNamespace(content=text, tool_calls=tool_calls or None, reasoning=None,
                              reasoning_content=None, reasoning_details=None)
    prompt = totals["fresh_input"] + totals["cache_read"]
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=totals["output"],
                            total_tokens=prompt + totals["output"],
                            prompt_tokens_details=SimpleNamespace(cached_tokens=totals["cache_read"]))
    # Hermes adds prompt_tokens to its session totals, and its compressor and context meter read the
    # current prompt from these fields instead.
    if context:
        usage.initial_prompt_tokens, usage.initial_cached_tokens = context.tokens, context.cache_read
    return SimpleNamespace(choices=[SimpleNamespace(message=message,
                                                    finish_reason="tool_calls" if tool_calls else "stop")],
                           usage=usage, model=model, **extra)


def projection(events: list[dict]) -> tuple[list[dict], int]:
    rows, steps = [], set()
    for event in events:
        message = event.get("message") or {}
        blocks = [b for b in message.get("content") or [] if isinstance(b, dict)]
        if event.get("type") == "assistant":
            calls = [b for b in blocks if b.get("type") == "tool_use"]
            if calls:
                steps.add(message.get("id"))
                rows.append({"role": "assistant", "content": "", "tool_calls": [
                    {"id": b["id"], "type": "function",
                     "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                    for b in calls]})
        elif event.get("type") == "user":
            rows += [{"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": text_of(b.get("content"))}
                     for b in blocks if b.get("type") == "tool_result"]
    return rows, len(steps)


def read_child_proposals(rows: list[dict]) -> bool:
    commands = {call["id"]: json.loads(call["function"]["arguments"]).get("command") or ""
                for row in rows for call in row.get("tool_calls") or []}
    return any(row["role"] == "tool" and CHILD_OUTPUT.search(commands.get(row["tool_call_id"], ""))
               and "Learning proposals" in row["content"] for row in rows)


# Hermes reviews memory every memory.nudge_interval user turns and never at session end, so proposals that
# arrive in a shorter session would never reach a memory review.
def queue_review(session_id: str) -> None:
    thread = resolve_session_env(session_id).get("BB_THREAD_ID")
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if not thread or not bb:
        logger.warning("%s: no bb thread for session %s, so its child proposals wait for the next review",
                       NAME, session_id)
        return
    # bb puts a sender header before a message from another thread, and Hermes runs /refine only when the
    # message starts with it.
    env = {k: v for k, v in os.environ.items() if k != "BB_THREAD_ID"}
    result = subprocess.run([bb, "thread", "tell", thread, "--mode", "queue", REFINE], env=env,
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.warning("%s: could not queue /refine on %s: %s", NAME, thread, (result.stderr or result.stdout).strip())


def running_agent(session_id: str):
    from gateway.run_api import _ACTIVE_RUNNER
    if _ACTIVE_RUNNER is None or not session_id:
        return None
    agents = _ACTIVE_RUNNER._snapshot_running_agents().values()
    return next((agent for agent in agents if getattr(agent, "session_id", None) == session_id), None)


class LiveProgress:
    def __init__(self, agent):
        self.agent = agent
        self.calls: dict[str, tuple[str, dict, float]] = {}
        self.answer_or_narration = ""

    def fire(self, name: str, *args, **kwargs) -> None:
        callback = getattr(self.agent, name, None)
        if callable(callback):
            callback(*args, **kwargs)

    def narrate(self) -> None:
        text, self.answer_or_narration = self.answer_or_narration.strip(), ""
        if text:
            self.fire("_emit_interim_assistant_message", {"role": "assistant", "content": text})

    def event(self, event: dict) -> None:
        kind = event.get("type")
        if kind not in ("assistant", "user"):
            return
        self.narrate()
        blocks = [b for b in (event.get("message") or {}).get("content") or [] if isinstance(b, dict)]
        if kind == "assistant":
            self.answer_or_narration = "\n\n".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
            for block in blocks:
                if block.get("type") == "tool_use":
                    self.narrate()
                    self.started(block)
        else:
            for block in blocks:
                if block.get("type") == "tool_result":
                    self.completed(block)

    def started(self, block: dict) -> None:
        call_id, name, args = block.get("id") or "", block.get("name") or "tool", block.get("input") or {}
        self.calls[call_id] = (name, args, time.monotonic())
        preview = next((str(args[k]) for k in ("command", "file_path", "pattern", "url", "description")
                        if args.get(k)), "")[:200]
        self.fire("tool_progress_callback", "tool.started", name, preview or None, args)
        self.fire("tool_start_callback", call_id, name, args)

    def completed(self, block: dict) -> None:
        call_id = block.get("tool_use_id") or ""
        name, args, started = self.calls.pop(call_id, ("tool", {}, None))
        result = text_of(block.get("content"))
        self.fire("tool_progress_callback", "tool.completed", name, None, None,
                  duration=None if started is None else time.monotonic() - started,
                  is_error=bool(block.get("is_error")), result=result)
        self.fire("tool_complete_callback", call_id, name, args, result)


class ClaudeCodeClient:
    HERMES_SKIP_TRANSPORT_WRAP = True
    HERMES_SKIP_ASYNC_WRAP = True

    def __init__(self, **_):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.is_closed = False
        self._lock = threading.Lock()
        self._running: set[subprocess.Popen] = set()
        self._cancelled: set[int] = set()

    def run(self, model: str, argv: list[str], prompt: str, cwd: str, session_id: str, env=None,
            progress: LiveProgress | None = None) -> tuple[dict, list[dict]]:
        child_env = {k: v for k, v in os.environ.items() if not GATEWAY_ONLY.match(k)}
        for name, value in resolve_session_env(session_id).items():
            if value is None:
                child_env.pop(name, None)
            else:
                child_env[name] = value
        child_env.update(env or {})
        process = subprocess.Popen([command_for(model), "-p", "--output-format", "stream-json", "--verbose", *argv],
                                   cwd=cwd, env=child_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        with self._lock:
            self._running.add(process)
        events: list[dict] = []
        try:
            errors: list[str] = []
            drain = threading.Thread(target=lambda: errors.append(process.stderr.read()), daemon=True)
            drain.start()
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except BrokenPipeError:
                pass
            for line in process.stdout:
                if not line.startswith("{"):
                    continue
                event = json.loads(line)
                events.append(event)
                if progress is not None:
                    progress.event(event)
            process.wait()
            drain.join()
            err = "".join(errors)
        finally:
            with self._lock:
                self._running.discard(process)
        if process.pid in self._cancelled:
            raise InterruptedError("Claude Code run cancelled")
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if process.returncode != 0 or result is None or result.get("is_error"):
            detail = (result or {}).get("result") or err.strip()[-800:] or f"exit {process.returncode}"
            raise RuntimeError(f"{command_for(model)} failed: {detail}")
        record_window(model, events, result)
        return result, events

    def cancel(self):
        with self._lock:
            running = tuple(self._running)
        for process in running:
            self._cancelled.add(process.pid)
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def close(self):
        self.is_closed = True
        self.cancel()

    def create(self, *, model: str, messages=None, tools=None, tool_choice=None, stream=False, extra_body=None, **_):
        messages = list(messages or [])
        context = (extra_body or {}).get(EXTRA_BODY_KEY) or {}
        key = context.get("session") or ""
        purpose = purpose_of(messages, tools)
        started = time.time()
        if purpose == "coding":
            answer, row = self.coding(model, messages, key, context)
        elif purpose == "review":
            answer, row = self.review(model, messages, tools, tool_choice, key, context)
        else:
            answer, row = self.auxiliary(model, messages, key, context)
        log_usage({"ts": round(started, 3), "seconds": round(time.time() - started, 1), "conversation": key,
                   "purpose": purpose, "model": model, "command": command_for(model), **row})
        return completion_to_stream_chunks(answer) if stream else answer

    def coding(self, model, messages, key, context):
        if not key:
            raise RuntimeError(f"{NAME}: the request carries no Hermes session id")
        current = role()
        if current.child and model.endswith("-astra"):
            raise RuntimeError(f"{NAME}: child coders do not run Astra models. Start the child with --model.")
        entry = conversation(key, str(resolve_agent_cwd()), current)
        argv = cache_prefix_flags(entry, model, context.get("effort"), sync_skills_plugin(current.learner_home))
        argv += ["--permission-mode", "bypassPermissions", "--settings", guard_settings(current)]
        argv += ["--resume" if transcript_exists(entry["session"]) else "--session-id", entry["session"]]
        agent = running_agent(key)
        result, events = self.run(model, argv, text_of(messages[-1].get("content")), entry["cwd"], key,
                                  progress=None if agent is None else LiveProgress(agent))
        rows, steps = projection(events)
        if not current.child and read_child_proposals(rows):
            queue_review(key)
        totals = usage_totals(result)
        answer = completion(result.get("result") or "", model, totals, context=last_call_prompt(events),
                            hermes_projected_messages=rows, hermes_provider_tool_iterations=steps)
        return answer, {"claude_session": entry["session"], **totals}

    def review(self, model, messages, tools, tool_choice, key, context):
        if role().child:
            raise RuntimeError(f"{NAME}: a child coder profile runs no review, because only its parent coder learns")
        path = runtime_dir() / "sessions.json"
        entry = json.loads(path.read_text(encoding="utf-8")).get(key) if path.is_file() else None
        if entry is None or not transcript_exists(entry["session"]):
            raise RuntimeError(f"{NAME}: review before any coding turn of conversation {key!r}")
        index = review_index(messages)
        fork_key: ForkKey = (key, index, hashlib.sha1(text_of(messages[index]["content"]).encode()).hexdigest())
        fork = _FORKS.get(fork_key)
        flags = cache_prefix_flags(entry, model, context.get("effort"), runtime_dir() / "skills-plugin")
        flags += ["--permission-mode", "dontAsk", "--settings", REVIEW_SETTINGS]
        if fork is None:
            prompt = "\n\n".join([text_of(messages[index]["content"]),
                                  *render_tool_bridge_sections(tools, tool_choice, allowlist=REVIEW_TOOLS), FORK_NOTE])
            argv = flags + ["--resume", entry["session"], "--fork-session"]
        else:
            results = [f'<tool_result id="{m.get("tool_call_id")}">\n{text_of(m.get("content"))}\n</tool_result>'
                       for m in messages[fork.sent:] if m.get("role") == "tool"]
            prompt = "Results of your Hermes tool calls:\n\n" + "\n\n".join(results) + "\n\n" + RESULTS_NOTE
            argv = flags + ["--resume", fork.session]
        env = {}
        if command_for(model) == "claudex":
            env["ANTHROPIC_CUSTOM_HEADERS"] = f"X-Claude-Code-Session-Id: {entry['session']}"
        result, _ = self.run(model, argv, prompt, entry["cwd"], key, env)
        fork_session = result.get("session_id") if fork is None else fork.session
        _FORKS[fork_key] = Fork(fork_session, len(messages))
        totals = usage_totals(result)
        calls, text = extract_tool_calls_from_text(result.get("result") or "")
        if not calls and "<tool_call>" in (result.get("result") or ""):
            result, _ = self.run(model, flags + ["--resume", fork_session], INVALID_CALL_NOTE, entry["cwd"], key, env)
            totals = {name: totals[name] + value for name, value in usage_totals(result).items()}
            calls, text = extract_tool_calls_from_text(result.get("result") or "")
        return completion(text, model, totals, calls), {"claude_session": fork_session,
                                                        "parent_session": entry["session"],
                                                        "tool_calls": [c.function.name for c in calls], **totals}

    def auxiliary(self, model, messages, key, context):
        system = "\n\n".join(text_of(m.get("content")) for m in messages if m.get("role") == "system")
        turns = [f"{m.get('role', 'user').capitalize()}:\n{text_of(m.get('content')).strip()}"
                 for m in messages if m.get("role") != "system" and text_of(m.get("content")).strip()]
        argv = ["--model", model, "--tools", "", "--no-session-persistence", "--strict-mcp-config",
                "--setting-sources", "", "--system-prompt", system or "You are a helpful assistant."]
        if context.get("effort"):
            argv += ["--effort", context["effort"]]
        result, _ = self.run(model, argv, "\n\n".join(turns), str(runtime_dir()), key,
                          {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
        totals = usage_totals(result)
        return completion(result.get("result") or "", model, totals), totals


def gpt_models() -> list[str]:
    config_path = Path(os.environ.get("CLAUDEX_CONFIG") or Path.home() / ".config/claudex/config.json")
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    key = os.environ.get("CLIPROXY_API_KEY") or config.get("apiKey") or ""
    reference = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", key)
    if reference:
        key = os.environ.get(reference[1], "")
    base = (os.environ.get("CLIPROXY_BASE_URL") or config.get("baseUrl") or "http://127.0.0.1:8317").rstrip("/")
    request = urllib.request.Request(base.removesuffix("/v1") + "/v1/models", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        catalog = json.load(response).get("data") or []
    ids = [m["id"] for m in catalog if isinstance(m, dict) and GPT_MODEL.match(str(m.get("id")))
           and m.get("owned_by") == "openai" and m.get("visibility") != "hide"]
    return sorted(ids, key=lambda model: [int(n) for n in re.findall(r"\d+", model)], reverse=True)


class ClaudeCodeProfile(ProviderProfile):
    def create_client(self, **client_kwargs):
        return ClaudeCodeClient(**client_kwargs)

    def build_api_kwargs_extras(self, *, reasoning_config=None, **context):
        body = {"session": context.get("session_id") or "", "effort": effort_of(reasoning_config)}
        return {EXTRA_BODY_KEY: body}, {}

    def fetch_models(self, **_):
        return [*CLAUDE_MODELS, *gpt_models()]

    def get_model_context_length(self, model: str) -> int | None:
        return known_windows().get(model) or self.model_capabilities.get(model, {}).get("context_window")


register_provider(ClaudeCodeProfile(
    name=NAME,
    display_name="Claude Code",
    description="Coding turns run in Claude Code. Claude models use claude, GPT models use claudex.",
    auth_type="external_process",
    process_command="claude",
    base_url=f"acp://{NAME}",
    supports_health_check=False,
    fallback_models=CLAUDE_MODELS,
    model_capabilities={name: {"supports_tools": True, "supports_reasoning": True, "supports_vision": False,
                               "context_window": 1_000_000} for name in CLAUDE_MODELS},
))
