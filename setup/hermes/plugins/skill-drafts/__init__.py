"""Block every skill_manage call. Hand a background review's proposals to an analyst agent.

Installed skills are copies of files that live in other repositories, so no call may change them.

A call from the operator's own conversation is sent back: the operator writes the brief itself, as
its operator-handoff skill describes, because only it knows why the skill fell short.

A call from Hermes's background skill review is recorded instead. That review runs in a fork whose
messages are never stored, so this plugin also keeps the reviewer's own text from each of its model
responses. When the review ends, one analyst bb thread receives an evidence packet with every
blocked call, its diff, the reviewer's text, and the stored conversation. The analyst decides
whether a change is warranted and, if so, creates a held draft that the user approves by sending.
The analyst and its draft are children of the operator thread that shows the session, when that
thread can be found.

Hooks only touch memory: Hermes abandons a hook after 30 s and then skips that hook for a while.
Every bb and hermes command runs on the plugin's own worker thread. Hermes treats an exception in
a hook as "proceed", so the hooks catch everything and still block.
"""

from __future__ import annotations

import contextvars
import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

SOURCES = Path(__file__).with_name("sources.json")
STATE = Path(__file__).resolve().parents[2] / "skill-drafts"
COMMAND_TIMEOUT_SECONDS = 120
MAX_DIFF_LINES = 400
IDLE_SECONDS = 10 * 60
KEEP_SECONDS = 14 * 24 * 3600
MAX_NOTE_CHARS = 8_000
MAX_NOTES_CHARS = 40_000
ANALYST_PROVIDER = "claude-code"
ANALYST_EFFORT = "high"
OPUS_ID = re.compile(r"claude-opus-(\d{1,2})(?:-(\d{1,2}))?")
BACKGROUND_REVIEW = "background_review"

FOREGROUND_BLOCK = (
    "Not applied. Skills are never changed with skill_manage here. Write the brief yourself with "
    "your observation and create the held draft as the operator-handoff skill describes.")
QUEUED_BLOCK = (
    "Not applied. This proposal is recorded. When this review ends, a separate agent reviews it "
    "with your messages from this review and decides whether to draft the change for the user's "
    "approval. In your final reply, state what in the conversation showed the skill falling short.")


@dataclass
class Turn:
    """What one review turn left behind: its blocked calls and the reviewer's text, in order."""
    session_id: str
    context: contextvars.Context
    calls: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    ended: bool = False
    last_seen: float = 0.0


def operations(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the call as a list of operations, accepting the legacy flat shape."""
    ops = args.get("operations")
    if isinstance(ops, list):
        return [op for op in ops if isinstance(op, dict)]
    return [args] if args.get("action") else []


def installed_file(sources: dict[str, Any], name: str, file_path: str | None) -> Path | None:
    skill = sources.get("skills", {}).get(name)
    if skill is None:
        return None
    return Path(skill["installed"]) / (file_path or "SKILL.md")


def installed_text(sources: dict[str, Any], op: dict[str, Any]) -> str:
    target = installed_file(sources, str(op.get("name", "")), op.get("file_path"))
    return target.read_text(encoding="utf-8") if target and target.is_file() else ""


def proposed_diff(sources: dict[str, Any], op: dict[str, Any]) -> str:
    """Unified diff of one operation against the installed copy, when it can be computed."""
    action = op.get("action")
    name = str(op.get("name", ""))
    file_path = op.get("file_path")
    before = installed_text(sources, op)
    if action == "create" or (action == "patch" and "content" in op and "old_string" not in op):
        after = str(op.get("content", ""))
    elif action == "write_file":
        after = str(op.get("file_content", ""))
    elif action == "patch" and before and op.get("old_string") in before:
        count = -1 if op.get("replace_all") else 1
        after = before.replace(str(op["old_string"]), str(op.get("new_string", "")), count)
    elif action in ("delete", "remove_file"):
        after = ""
    else:
        return ""
    label = f"{name}/{file_path or 'SKILL.md'}"
    lines = list(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{label}", tofile=f"b/{label}"))
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"... diff truncated after {MAX_DIFF_LINES} lines\n"]
    return "".join(lines)


def fingerprint(sources: dict[str, Any], op: dict[str, Any]) -> str:
    """The same operation on the same installed file. A changed skill makes an old proposal new again."""
    baseline = hashlib.sha256(installed_text(sources, op).encode()).hexdigest()
    canonical = json.dumps(op, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{baseline}\n{canonical}".encode()).hexdigest()


def owner(sources: dict[str, Any], name: str) -> str:
    """Where a change to the skill starts. Unknown names are new skills for the default repository."""
    skill = sources.get("skills", {}).get(name)
    if skill is None:
        return f"a new skill. Place it in `{sources['defaultRepo']}` where that repository's docs say"
    if skill.get("upstream"):
        return (f"`{skill['path']}` in {skill['upstream']} at `{skill['commit']}`, pinned in "
                f"`.claude-plugin/marketplace.json` of `{skill['repo']}`. Change the fork, then update the "
                f"pin as that repository's `docs/upstream-skills.md` describes")
    return f"`{skill['path']}` in `{skill['repo']}`"


def skill_names(ops: list[dict[str, Any]]) -> list[str]:
    return sorted({str(op.get("name", "")) for op in ops})


def message_text(message: Any) -> str:
    """The reviewer's words in one model response: reasoning, text, and the tools it called."""
    parts = []
    reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
    if isinstance(reasoning, str) and reasoning.strip():
        parts.append(f"(reasoning) {reasoning.strip()}")
    content = getattr(message, "content", None)
    if isinstance(content, list):
        content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    for call in getattr(message, "tool_calls", None) or []:
        function = getattr(call, "function", None) or (call.get("function") if isinstance(call, dict) else None)
        name = getattr(function, "name", None) or (function.get("name") if isinstance(function, dict) else None)
        arguments = getattr(function, "arguments", None) or (
            function.get("arguments") if isinstance(function, dict) else None)
        if name:
            parts.append(f"(called {name}) {str(arguments or '')[:300]}")
    return "\n".join(parts)[:MAX_NOTE_CHARS]


def write_origin() -> str:
    try:
        from tools.write_approval import current_origin
        return current_origin()
    except Exception:
        return "unknown"


def operator_thread(session_id: str) -> str | None:
    """The bb thread that shows the session, from the bb-thread-env plugin's session env."""
    try:
        from hermes_cli.plugins_session_env import resolve_session_env
        return resolve_session_env(session_id).get("BB_THREAD_ID") or None
    except Exception:
        logger.warning("skill-drafts: could not resolve the bb thread of session %s", session_id, exc_info=True)
        return None


def bb_path() -> str:
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if not bb:
        raise RuntimeError("the bb CLI is not on the gateway's PATH and BB_CLI is unset")
    return bb


def run(command: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(command[1:4])}` failed: {(result.stderr or result.stdout).strip()[:500]}")
    return result.stdout


def analyst_model(models: Any) -> str:
    """The highest-numbered Opus ID without a suffix that lists the analyst's effort."""
    listed = models if isinstance(models, list) else models.get("models", [])
    candidates = []
    for model in listed:
        found = OPUS_ID.fullmatch(str(model.get("id", "")))
        efforts = {e.get("reasoningEffort") for e in model.get("supportedReasoningEfforts", [])}
        if found and ANALYST_EFFORT in efforts:
            candidates.append(((int(found[1]), int(found[2] or 0)), model["id"]))
    if not candidates:
        raise RuntimeError(f"{ANALYST_PROVIDER} lists no Opus model with {ANALYST_EFFORT} effort")
    return max(candidates)[1]


class Ledger:
    """Proposals an analyst already received, by fingerprint. Only the worker thread writes it."""

    def __init__(self, path: Path):
        self.path = path

    def load(self, now: float) -> dict[str, dict[str, Any]]:
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {fp: entry for fp, entry in entries.items() if now - entry.get("at", 0) < KEEP_SECONDS}

    def save(self, entries: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_suffix(".tmp")
        partial.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
        os.replace(partial, self.path)


class Proposals:
    """Collects each review turn in memory and, on the worker thread, hands it to one analyst."""

    def __init__(self, state: Path, sources_path: Path, clock: Callable[[], float] = time.time):
        self.state = state
        self.sources_path = sources_path
        self.clock = clock
        self.ledger = Ledger(state / "ledger.json")
        self.turns: dict[str, Turn] = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopping = False
        self.worker: threading.Thread | None = None

    def turn(self, turn_id: str, session_id: str) -> Turn:
        """The turn's record, created with the caller's context so the parent resolves in its profile."""
        turn = self.turns.get(turn_id)
        if turn is None:
            turn = self.turns[turn_id] = Turn(session_id, contextvars.copy_context())
        turn.last_seen = self.clock()
        return turn

    def record_call(self, turn_id: str, session_id: str, args: dict[str, Any]) -> None:
        with self.lock:
            if turn_id:
                self.turn(turn_id, session_id).calls.append(args)
            else:
                turn = self.turn(f"no-turn:{uuid.uuid4().hex}", session_id)
                turn.calls.append(args)
                turn.gaps.append("Hermes gave this call no turn id, so the reviewer's messages could not be "
                                 "matched to it and other calls of the same review arrive separately.")
                turn.ended = True
        self.poke()

    def record_note(self, turn_id: str, session_id: str, text: str, final: bool) -> None:
        if not turn_id:
            return
        with self.lock:
            turn = self.turn(turn_id, session_id)
            if text:
                turn.notes.append(text)
                while sum(map(len, turn.notes)) > MAX_NOTES_CHARS and len(turn.notes) > 1:
                    turn.notes.pop(0)
                    if not turn.gaps or not turn.gaps[-1].startswith("The reviewer's earliest"):
                        turn.gaps.append("The reviewer's earliest messages were dropped to keep the packet small.")
            turn.ended = turn.ended or final
        if final:
            self.poke()

    def due(self, now: float, everything: bool) -> list[tuple[str, Turn]]:
        """Remove and return the turns that ended or went quiet. Turns without calls are dropped."""
        with self.lock:
            ready = [key for key, turn in self.turns.items()
                     if everything or turn.ended or now - turn.last_seen >= IDLE_SECONDS]
            taken = [(key, self.turns.pop(key)) for key in ready]
        for key, turn in taken:
            if turn.calls and not turn.ended:
                turn.gaps.append(f"The review sent no final response within {IDLE_SECONDS // 60} minutes of its "
                                 "last message, so its closing summary is missing.")
        return [(key, turn) for key, turn in taken if turn.calls]

    def flush_due(self, now: float | None = None, everything: bool = False) -> list[str]:
        """Hand every finished turn to an analyst. Returns one outcome line per turn."""
        now = self.clock() if now is None else now
        return [self.dispatch(key, turn, now) for key, turn in self.due(now, everything)]

    def dispatch(self, turn_id: str, turn: Turn, now: float) -> str:
        key = hashlib.sha256(turn_id.encode()).hexdigest()[:12]
        parent = None
        names: list[str] = []
        try:
            sources = json.loads(self.sources_path.read_text(encoding="utf-8"))
            ops = [op for args in turn.calls for op in operations(args)]
            if not ops:
                return f"empty {key}: the calls name no operation"
            names = skill_names(ops)
            entries = self.ledger.load(now)
            prints = {fingerprint(sources, op) for op in ops}
            if prints <= entries.keys():
                earlier = sorted({entries[fp].get("thread") or "unknown" for fp in prints})
                logger.info("skill-drafts: review %s repeats proposals already given to %s", key, earlier)
                return f"duplicate {key}: {', '.join(earlier)}"
            parent = turn.context.run(operator_thread, turn.session_id)
            packet = self.write_packet(key, turn, sources, ops, entries, parent, now)
            bb = bb_path()
            model = analyst_model(json.loads(run([bb, "provider", "models", ANALYST_PROVIDER, "--json"])))
            command = [bb, "thread", "spawn", "--json", "--project", sources["researchProject"],
                       "--new-environment", "personal", "--provider", ANALYST_PROVIDER, "--model", model,
                       "--reasoning-level", ANALYST_EFFORT,
                       "--title", f"Skill proposal: {', '.join(names) or 'unknown'} [{key}]", "--prompt-file", "-"]
            if parent:
                command += ["--parent-thread", parent]
            thread = json.loads(run(command, analyst_brief(sources, turn, packet, parent)))["id"]
            for fp in prints:
                entries[fp] = {"at": now, "thread": thread, "review": key, "skills": names}
            self.ledger.save(entries)
            return f"spawned {key}: {thread}"
        except Exception as error:
            logger.warning("skill-drafts: no analyst started for review %s (%s): %s", key, names, error)
            self.report_failure(key, names, parent, error)
            return f"failed {key}: {error}"

    def write_packet(self, key: str, turn: Turn, sources: dict[str, Any], ops: list[dict[str, Any]],
                     entries: dict[str, dict[str, Any]], parent: str | None, now: float) -> Path:
        """Write the analyst's evidence files and return their directory."""
        for old in (self.state / "proposals").glob("*"):
            if now - old.stat().st_mtime >= KEEP_SECONDS:
                shutil.rmtree(old, ignore_errors=True)
        packet = self.state / "proposals" / key
        packet.mkdir(parents=True, exist_ok=True)
        gaps = list(turn.gaps)
        if not parent:
            gaps.append("No bb thread shows this Hermes session, so no operator thread will hear the result.")
        if not turn.notes:
            gaps.append("No message of the reviewer was captured.")
        session = packet / "session.jsonl"
        try:
            hermes = shutil.which("hermes")
            if not hermes:
                raise RuntimeError("the hermes CLI is not on the gateway's PATH")
            run([hermes, "-p", sources["profile"], "sessions", "export", "--format", "jsonl",
                 "--session-id", turn.session_id, str(session)])
        except Exception as error:
            gaps.append(f"Exporting the stored conversation failed: {error}. Run `hermes -p {sources['profile']} "
                        f"sessions export --format jsonl --session-id {turn.session_id} <file>` yourself.")
        skills = set(skill_names(ops))
        earlier = sorted({(e.get("thread") or "unknown", e.get("review", "")) for fp, e in entries.items()
                          if skills & set(e.get("skills", []))})
        repeats = [op for op in ops if fingerprint(sources, op) in entries]
        lines = [f"# Evidence for skill proposal review {key}", "",
                 f"Hermes session: `{turn.session_id}` (profile `{sources['profile']}`)",
                 f"Operator thread: {f'@thread:{parent}' if parent else 'none found'}", "",
                 "## Known gaps", "", *([f"- {gap}" for gap in gaps] or ["- None known."]), "",
                 "## Skills and their sources", "", *[f"- `{name}`: {owner(sources, name)}" for name in sorted(skills)],
                 "", "## Blocked skill_manage calls, in order", ""]
        for number, args in enumerate(turn.calls, 1):
            lines += [f"### Call {number}", "", "```json", json.dumps(args, indent=2, ensure_ascii=False), "```", ""]
            diffs = [d.rstrip("\n") for d in (proposed_diff(sources, op) for op in operations(args)) if d]
            if diffs:
                lines += ["Diff against the installed copy:", "", "```diff", *diffs, "```", ""]
        if repeats:
            lines += ["Operations in these calls that an earlier analyst already received:", "",
                      *[f"- `{op.get('action')}` on `{op.get('name')}`" for op in repeats], ""]
        lines += ["## The reviewer's messages, oldest first", "",
                  "Captured from the background review's model responses. Hermes never stores them.", ""]
        for number, note in enumerate(turn.notes, 1):
            lines += [f"### Message {number}", "", note, ""]
        lines += ["## Earlier proposal reviews for the same skills (last 14 days)", "",
                  *([f"- @thread:{thread} (review {review})" for thread, review in earlier] or ["- None."]), ""]
        (packet / "evidence.md").write_text("\n".join(lines), encoding="utf-8")
        return packet

    def report_failure(self, key: str, names: list[str], parent: str | None, error: Exception) -> None:
        """Tell the operator thread, which tells the user. Without one, the gateway log is the record."""
        if not parent:
            return
        message = (f"[skill-drafts plugin] Hermes's background skill review proposed changes to "
                   f"{', '.join(names) or 'unknown skills'}. The changes were blocked and nothing was changed, "
                   f"but no analyst could be started to review the proposal: {error}. The evidence is in "
                   f"{self.state / 'proposals' / key}. Tell the user. A later review that proposes the same "
                   f"change tries again.")
        try:
            run([bb_path(), "thread", "tell", parent, "--mode", "auto", "--message-file", "-"], message)
        except Exception as tell_error:
            logger.warning("skill-drafts: could not tell thread %s about review %s: %s", parent, key, tell_error)

    def poke(self) -> None:
        """Wake the worker, starting it on first use. Never blocks."""
        with self.lock:
            if self.worker is None and not self.stopping:
                self.worker = threading.Thread(target=self.serve, name="skill-drafts", daemon=True)
                self.worker.start()
        self.wake.set()

    def serve(self) -> None:
        while not self.stopping:
            self.wake.wait(60)
            self.wake.clear()
            self.flush_due()
        self.flush_due(everything=True)

    def stop(self) -> None:
        """On unload: the worker hands over whatever was collected, then exits."""
        self.stopping = True
        self.wake.set()


PROPOSALS = Proposals(STATE, SOURCES)


def analyst_brief(sources: dict[str, Any], turn: Turn, packet: Path, parent: str | None) -> str:
    handoff = Path(sources["skillsDir"]) / "operator-handoff" / "SKILL.md"
    parenting = (f"Right after creating the draft, make it a child of the operator thread: "
                 f"`bb thread update <draftId> --parent-thread {parent}`. Never make it a child of your own "
                 f"thread, because archiving you would archive it." if parent else
                 "No operator thread was found, so leave the draft top-level and say so in your final message.")
    return "\n".join([
        f"Read {sources['modePath']} and follow it for this task.",
        "",
        "## Goal",
        "",
        "Decide whether the skill change that Hermes's automatic background skill review proposed is "
        "warranted. If the evidence supports it, prepare it as a held bb draft for a coding agent, which "
        "the user approves by sending. If it does not, create nothing and say why. State your confidence "
        "either way.",
        "",
        "## Context",
        "",
        f"After a turn of Hermes session `{turn.session_id}` (profile `{sources['profile']}`), Hermes's "
        "background skill review called `skill_manage`. The skill-drafts plugin blocked every call, so "
        "nothing changed, and started you.",
        "",
        f"- `{packet / 'evidence.md'}`: the blocked calls with raw arguments, diffs against the installed "
        "copies, where each skill's source lives, the reviewer's own messages captured from its model "
        "responses, the known gaps, and earlier proposal reviews for the same skills.",
        f"- `{packet / 'session.jsonl'}`: the stored conversation of the session. It holds the foreground "
        "turns only. The review's reasoning exists only in the evidence file.",
        f"- `{sources['sourcesPath']}`: every installed skill and the repository it comes from.",
        f"- Operator thread: {f'@thread:{parent}' if parent else 'none found'}.",
        "",
        "The reviewer is told to be active, so many of its proposals are generic. Treat the calls as a "
        "hypothesis, not as an observed defect.",
        "",
        "## Constraints",
        "",
        "- Do not edit files, commit, push, or install anything. Do not run `skill_manage`, `mise`, or a "
        "`hermes` command that changes state.",
        "- The only bb changes you may make are one `bb draft create` per repository that owns a warranted "
        "change, and the parent update below. Never send a draft, never change plugin settings, and never "
        "message, update, or archive another thread.",
        "- A change goes ahead only when you can point to what in the conversation or the reviewer's "
        "messages shows the skill falling short. Merge related calls into one change. Drop speculative or "
        "generic edits.",
        "- Before creating a draft, look for an open draft that covers the change: list threads with "
        "`bb thread list --json` and read those titled `Skill change:` with `bb thread show <id> --json` "
        "and `bb thread queue list <id> --json`. If one covers it, create nothing and name it.",
        "- Run `bb plugin config held-drafts --json` before creating a draft. If `values.mode` is not "
        "`draft`, a draft would start at once without the user's approval, so create none and put the "
        "complete brief in your final message instead.",
        "",
        "## Writing the draft",
        "",
        f"Follow the sections \"Write the brief\", \"Choose the route\", and \"Create the draft\" of `{handoff}`, "
        "the operator's own instructions, with these differences:",
        "",
        "- Route the coding worker by the `ramtoshiya:worker-routing` skill as the session that delegates.",
        "- Title it `Skill change: <skill names>`.",
        "- Add a \"Confidence and gaps\" section to the brief: your confidence, what you inferred rather "
        "than observed, and what evidence would change the decision.",
        f"- {parenting}",
        "",
        "## Expected result",
        "",
        "Your final message is the result. Give the decision (`@thread:<draftId>` held, none, or covered by "
        "`@thread:<id>`), the observations with their sources, your inferences kept separate, your "
        "confidence (high, medium, or low) with what would change it, and the draft's row, provider, model, "
        "and effort.",
        "",
    ])


def on_pre_tool_call(tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any):
    if tool_name != "skill_manage":
        return None
    try:
        if write_origin() != BACKGROUND_REVIEW:
            return {"action": "block", "message": FOREGROUND_BLOCK}
        PROPOSALS.record_call(str(kwargs.get("turn_id") or ""), str(kwargs.get("session_id") or ""),
                              args if isinstance(args, dict) else {})
    except Exception as error:  # fail closed: any error still blocks the write
        return {"action": "block", "message": (
            f"Blocked. Skills are not changed locally, and recording this proposal failed: {error}. "
            f"Do not retry through another tool.")}
    return {"action": "block", "message": QUEUED_BLOCK}


def on_post_api_request(session_id: str = "", turn_id: str = "", assistant_message: Any = None,
                        assistant_tool_call_count: int = 0, **_: Any) -> None:
    try:
        if write_origin() == BACKGROUND_REVIEW:
            PROPOSALS.record_note(str(turn_id or ""), str(session_id or ""), message_text(assistant_message),
                                  final=not assistant_tool_call_count)
    except Exception:
        logger.warning("skill-drafts: could not record a review message", exc_info=True)


def reload_arguments(parser) -> None:
    parser.add_argument("action", choices=["reload"])


def reload_plugins(_args) -> int:
    """`hermes -p <profile> skill-drafts reload`: the gateway serving the profile imports its plugins'
    current files. Enabling an already enabled plugin does not, so a reinstall needs this.
    Prints the gateway's answer as JSON, or null when no gateway answered."""
    from hermes_cli.plugins_activation import reload_running_gateway
    print(json.dumps(reload_running_gateway()))
    return 0


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_api_request", on_post_api_request)
    ctx.on_unload(PROPOSALS.stop)
    ctx.register_cli_command("skill-drafts", "Load this profile's current plugin files into the running gateway",
                             reload_arguments, reload_plugins)
