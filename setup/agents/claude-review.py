#!/usr/bin/env python3
"""Run Claude Code with a time budget for each user turn.

Launcher mode, for any arguments except `hook`: fold every --settings value and
the budget hooks into one settings object, then exec `claude`. Claude Code keeps
only the last --settings flag, so a second flag would drop the caller's.

Hook mode, `claude-review.py hook` with the event JSON on stdin: keep a turn
clock per session. After the warning time the model gets one reminder. After the
budget, the next tool call is denied once and every later one stops the turn.
A failure prints one line to stderr and exits 0, so a bug never blocks a review.

CLAUDE_REVIEW_MINUTES (default 30) and CLAUDE_REVIEW_WARN_MINUTES (default 20)
set the budget. Both accept decimals.
"""
import fcntl
import json
import math
import os
import re
import signal
import sys
import tempfile
import time

EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse")
BUDGET_VARIABLES = (("CLAUDE_REVIEW_MINUTES", "30"), ("CLAUDE_REVIEW_WARN_MINUTES", "20"))
INFO_FLAGS = ("--version", "-v", "--help", "-h")
UV_COMMAND = ("uv run --offline --no-project --managed-python --python '>=3.11' "
              "--no-config --exclude-newer '3 days' python -I")
HOOK_TIMEOUT_SECONDS = 10
SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")


class LaunchError(Exception):
    """A problem worded for the person who ran the launcher. It never holds a --settings value."""


def reject_constant(name):
    # Node's JSON.parse refuses NaN and Infinity, and tools/claudex/claudex.cjs relies on that.
    raise ValueError(name)


def read_settings(value):
    """Parse one --settings value: inline JSON if it starts with `{`, otherwise a file path."""
    try:
        if value.lstrip().startswith("{"):
            text = value
        else:
            with open(value, encoding="utf-8") as file:
                text = file.read()
        settings = json.loads(text, parse_constant=reject_constant)
    except (OSError, ValueError, RecursionError):
        raise LaunchError("--settings must be a JSON object or the path of a JSON file.") from None
    if not isinstance(settings, dict) or not isinstance(settings.get("env", {}), dict):
        raise LaunchError("--settings must be a JSON object with an object env.")
    return settings


def take_settings(args):
    """Remove the --settings options in front of `--` and merge them in order.

    Returns the other arguments and the merged settings. Later keys win and `env`
    merges key by key, as in tools/claudex/claudex.cjs. A trailing --settings without
    a value stays in place for claude to reject.
    """
    rest, merged, env = [], {}, None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            rest.extend(args[i:])
            break
        if arg == "--settings" and i + 1 < len(args):
            value, i = args[i + 1], i + 2
        elif arg.startswith("--settings="):
            value, i = arg[len("--settings="):], i + 1
        else:
            rest.append(arg)
            i += 1
            continue
        settings = read_settings(value)
        merged.update(settings)
        if "env" in settings:
            env = {**(env or {}), **settings["env"]}
    if env is not None:
        merged["env"] = env
    return rest, merged


def shell_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def add_hooks(settings, script):
    """Append the budget hooks to settings["hooks"] and keep the caller's entries."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict) or not all(isinstance(hooks.get(event, []), list) for event in EVENTS):
        raise LaunchError("--settings hooks must be an object, and its event entries must be lists.")
    command = f"{UV_COMMAND} {shell_quote(script)} hook"
    for event in EVENTS:
        hooks.setdefault(event, []).append(
            {"hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT_SECONDS}]})


def parse_minutes(name, text):
    try:
        minutes = float(text)
    except ValueError:
        minutes = math.nan
    if not math.isfinite(minutes) or minutes <= 0:
        raise LaunchError(f"{name} must be a number of minutes above 0.")
    return minutes


def read_budget(environ):
    """Return the budget and the warning time in minutes."""
    budget, warning = (parse_minutes(name, environ.get(name, default)) for name, default in BUDGET_VARIABLES)
    if warning >= budget:
        raise LaunchError("CLAUDE_REVIEW_WARN_MINUTES must be less than CLAUDE_REVIEW_MINUTES.")
    return budget, warning


def without_uv_directory(path):
    """Drop the interpreter directory that `uv run` puts first on PATH.

    Left in place, it would make `python3` in the review session resolve to uv's
    managed Python instead of the caller's.
    """
    entries = path.split(os.pathsep)
    if entries[0] and os.path.realpath(entries[0]) == os.path.realpath(os.path.dirname(sys.executable)):
        entries = entries[1:]
    return os.pathsep.join(entries)


def exec_claude(args, env):
    # Python ignores these signals, and an ignored signal stays ignored across exec.
    for name in ("SIGPIPE", "SIGXFSZ"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_DFL)
    try:
        os.execvpe("claude", ["claude", *args], env)
    except OSError:
        raise LaunchError("Could not start claude. Install Claude Code and put it on PATH.") from None


def launch(args):
    if len(args) == 1 and args[0] in INFO_FLAGS:
        exec_claude(args, os.environ)
    rest, settings = take_settings(args)
    read_budget(os.environ)
    add_hooks(settings, os.path.abspath(__file__))
    env = dict(os.environ)
    for name, default in BUDGET_VARIABLES:
        env.setdefault(name, default)
    if "PATH" in env:
        env["PATH"] = without_uv_directory(env["PATH"])
    exec_claude(["--settings", json.dumps(settings, separators=(",", ":")), *rest], env)


def minutes_text(minutes):
    return f"{minutes:.2f}".rstrip("0").rstrip(".")


def new_state(now):
    return {"started": now, "warned": False, "denied": False}


def step(name, state, now, budget, warning):
    """Apply one hook event to the turn state. Return the hook output, or None."""
    used = (now - state["started"]) / 60
    if name == "PostToolUse" and used >= warning and not state["warned"]:
        state["warned"] = True
        text = (f"Review time: {minutes_text(used)} of {minutes_text(budget)} minutes used. "
                "Finish the check you are on, then write your report. Do not start new checks. "
                "Tool calls are refused once the time is up.")
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}
    if name == "PreToolUse" and used >= budget:
        text = (f"The review time budget of {minutes_text(budget)} minutes is used up, so no more tools "
                "may be called. Write your report now from what you have, and list what you did not check.")
        refusal = {"hookSpecificOutput": {"hookEventName": name, "permissionDecision": "deny",
                                          "permissionDecisionReason": text}}
        if state["denied"]:
            # `continue: false` alone ends the turn but still runs the call that triggered it.
            return {"continue": False,
                    "stopReason": f"Review time budget of {minutes_text(budget)} minutes is used up.",
                    **refusal}
        state["denied"] = True
        return refusal
    return None


def read_state(fd, now):
    """Return the stored state, or one starting now when the file is new or unreadable."""
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        stored = json.loads(os.read(fd, 4096), parse_constant=reject_constant)
        return {"started": float(stored["started"]), "warned": bool(stored["warned"]),
                "denied": bool(stored["denied"])}
    except (ValueError, KeyError, TypeError):
        return new_state(now)


def write_state(fd, state):
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(state).encode())


def handle(event, environ, now):
    """Return the JSON object the hook prints for this event, or None for no output."""
    if not isinstance(event, dict):
        raise ValueError("the event is not a JSON object")
    name, session_id = event.get("hook_event_name"), event.get("session_id")
    if name not in EVENTS:
        raise ValueError("unsupported hook event")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise ValueError("session_id is not made of letters, digits, - and _")
    budget, warning = read_budget(environ)
    directory = os.path.join(tempfile.gettempdir(), "claude-review")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(directory, f"{session_id}.json"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        # The tool calls of one assistant message run their hooks at the same time.
        # The lock leaves exactly one of them as the first call after the budget.
        fcntl.flock(fd, fcntl.LOCK_EX)
        state = new_state(now) if name == "UserPromptSubmit" else read_state(fd, now)
        output = step(name, state, now, budget, warning)
        write_state(fd, state)
        return output
    finally:
        os.close(fd)


def run_hook():
    try:
        output = handle(json.load(sys.stdin), os.environ, time.time())
    except Exception as error:  # A bug in a hook must never block the review.
        print(f"claude-review: hook skipped: {' '.join(str(error).split()) or type(error).__name__}",
              file=sys.stderr)
        return
    if output is not None:
        print(json.dumps(output))


def main():
    args = sys.argv[1:]
    if args == ["hook"]:
        run_hook()
        return
    try:
        launch(args)
    except LaunchError as error:
        print(f"claude-review: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
