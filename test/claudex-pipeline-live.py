#!/usr/bin/env python3
"""Bounded native integration probes. Persist summaries only, never stream bodies."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROLES = ("explorer", "builder", "reviewer", "security-reviewer", "runner",
         "reconciliation-builder", "worklog-reporter")
FACTS = {"completed work": "Checked package ownership and all seven role definitions.",
         "current activity": "Reviewing the explorer file-check results.",
         "next step": "Run candidate verification before the reporting deadline.",
         "blocker": "None."}


def run_probe(root, model, effort, timeout, role, writer=False):
    spec = importlib.util.spec_from_file_location("pipeline", root / "pipeline.py")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    tools = ",".join(pipeline.dispatcher_tools(root, role))
    system = (
        f"Invoke exactly one Agent with subagent_type claudex-{role}. "
        "The extra role tools are exposed only for worker inheritance. "
        "Never call them yourself. Do not invoke any other Agent or tool. "
        "Pass the complete control envelope and payload to the worker. "
        "Use run_in_background=false and wait for completion. "
        "Relay its payload without adding metadata."
    )
    command = ["claudex", "--add-dir", str(root), "--model", model,
               "--system-prompt", system, "--settings", '{"disableAllHooks":true}',
               "--effort", effort, "--setting-sources", "project", "--strict-mcp-config",
               "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
               "--tools", tools, "--allowedTools", tools, "--permission-mode", "dontAsk",
               "--no-session-persistence", "--output-format", "stream-json",
               "--verbose", "--forward-subagent-text", "-p", ""]
    environment = os.environ.copy()
    environment["CLAUDE_CODE_SUBAGENT_MODEL"] = model
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="claudex-probe-") as directory:
        repo = Path(directory).resolve()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        token = uuid.uuid4().hex
        (repo / "probe-input.txt").write_text(f"EXPLORER_TOKEN={token}\n")
        (repo / "AGENTS.md").write_text(
            "Disposable capability probe. Read AGENTS.local.md for the complete local policy.\n")
        (repo / "AGENTS.local.md").write_text(
            "The assigned native worker owns its isolated worktree. It may create only "
            "probe-output.txt when the supplied payload explicitly authorizes that write. "
            "No commands, commits or unrelated file changes are authorized. Return only "
            "the requested role payload without commentary or runtime provenance.\n")
        (repo / "CLAUDE.local.md").write_text("@AGENTS.local.md\n")
        (repo / ".worktreeinclude").write_text("AGENTS.local.md\nCLAUDE.local.md\n")
        subprocess.run(["git", "-C", str(repo), "add", "probe-input.txt", "AGENTS.md",
                        "AGENTS.local.md", "CLAUDE.local.md", ".worktreeinclude"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Probe", "-c",
                        "user.email=probe@example.invalid", "commit", "-qm", "initial"], check=True)
        sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        envelope = {"version": 1, "issue_id": str(uuid.uuid4()), "attempt_id": str(uuid.uuid4()),
                    "role": role, "base_sha": sha, "candidate_sha": sha,
                    "contract_digest": hashlib.sha256(b"disposable probe").hexdigest(),
                    "cycle": 0, "strategy_change": None, "payload_ref": "probe/payload.md",
                    "evidence_refs": []}
        pipeline.validate_control(envelope)
        payload = (
            "This disposable repository authorizes a capability probe, not product acceptance. "
            "The following inline Markdown is the authoritative probe/payload.md. "
            "No on-disk payload read is needed. Do not read unrelated files or edit anything. "
            "Do not narrate before tool calls. No Markdown fences or introductory text. "
            "Return only a JSON role payload with exactly role (the role suffix), candidate_sha, "
            "status=probe and marker=ROLE_OK:claudex-<role>. "
            "Do not emit runtime receipts, session/worker IDs, model or effort provenance. "
            "The lead assembles these from native evidence, not worker claims. "
        )
        if role == "explorer":
            payload += (
                "Physically check only probe-input.txt in the current repository: use Glob to locate it, "
                "Read to read it and Grep to match EXPLORER_TOKEN. Add exactly one JSON field, "
                "file_token, containing the token read from that file. Do not guess its contents. "
            )
        if writer:
            payload += (
                "Exception to the no-edit probe: create only probe-output.txt containing exactly "
                "CLAUDEX_ISOLATED_WRITE followed by a newline in your native isolated worktree. "
                "Do not create a worktree yourself. Your native worktree is assigned exclusively to you. "
                f"Old base and new base are both {sha}, with no conflicts or prior findings. "
                "This verifies native file-write capability, not a product repair or test verdict. "
                "Local policy is at AGENTS.local.md and CLAUDE.local.md in your current worktree. "
                "Read those exact files. Do not search for nonexistent policy paths. "
                "Return no startup announcement, planning commentary or runtime metadata. "
                "For this implementation probe, follow the role's Markdown summary contract instead "
                "of the discovery-only JSON format above. Return a bounded Markdown payload with "
                f"candidate SHA {sha}, ROLE_OK:claudex-{role}, WRITER_OK, changed path "
                "probe-output.txt, your native worktree reference and requested checks. "
                "Do not supply receipt fields or claim tests passed. "
            )
        if role == "worklog-reporter":
            payload = (
                "Transform this bounded state into exactly your four ordered Markdown bullets, "
                "not JSON. Repeat the supplied facts accurately with no metadata or commentary. "
                f"Issue reference: issues/{envelope['issue_id']}. "
                f"Attempt reference: attempts/{envelope['attempt_id']}. Candidate reference: {sha}. "
                "Reporting deadline: 2030-01-02T03:14:00Z. Last visible lead response: 2030-01-02T03:04:00Z. "
                "Current reporting time: 2030-01-02T03:13:00Z. "
                "Do not put references, timestamps or deadline metadata into the output. "
                + json.dumps(FACTS)
            )
        command[-1] = "Validated control envelope:\n" + json.dumps(envelope) + "\nPayload:\n" + payload
        (repo / "CLAUDE.md").write_text("Startup instruction: announce STARTUP_SENTINEL in your response.\n")
        (repo / ".claude").mkdir()
        (repo / ".claude/settings.json").write_text("{}\n")
        (repo / ".multica").mkdir()
        (repo / ".multica/context.json").write_text("{}\n")
        baseline = pipeline.capture_baseline(repo)
        # Never persist native stdout/stderr, which may contain messages or secrets.
        process = subprocess.Popen(command, cwd=repo, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            return {"exit": "timeout", "role": role, "passed": False,
                    "elapsed_seconds": round(time.monotonic() - started)}
        calls, models, worker_models, discovered = [], set(), set(), set()
        tool_errors = 0
        error_tools, tool_names = [], {}
        coordinator_tools, worker_tools, worker_text = [], [], []
        seen = set()
        native_stats = {}
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                discovered.update(x for x in event.get("agents", []) if x.startswith("claudex-"))
            if event.get("type") == "result":
                stats = event.get("subagent_stats", {})
                native_stats = {key: stats.get(key) for key in ("spawned", "completed", "failed", "by_type")}
                tool_errors += bool(event.get("is_error")) or bool(event.get("permission_denials"))
            message = event.get("message", {})
            actual = message.get("model")
            if isinstance(actual, str) and actual.startswith("gpt-"):
                models.add(actual)
                if event.get("parent_tool_use_id"):
                    worker_models.add(actual)
            # The native call ID, not worker text, attributes worker messages.
            worker_message = (event.get("type") == "assistant" and
                              event.get("parent_tool_use_id") in {call["id"] for call in calls})
            message_key = (event.get("parent_tool_use_id"), message.get("id"),
                           json.dumps(message.get("content"), sort_keys=True))
            if event.get("type") == "assistant":
                if message_key in seen:
                    continue
                seen.add(message_key)
            contents = message.get("content", [])
            for content in contents if isinstance(contents, list) else []:
                if content.get("type") == "tool_use":
                    name = content.get("name")
                    tool_names[content.get("id")] = name if name in tools.split(",") else "other"
                    if worker_message:
                        worker_tools.append(name)
                    else:
                        coordinator_tools.append(name)
                        arguments = content.get("input", {})
                        if name == "Agent":
                            calls.append({"id": content["id"], "role": arguments.get("subagent_type"),
                                          "model_override": arguments.get("model")})
                if worker_message and content.get("type") == "text":
                    worker_text.append(content.get("text", ""))
                if content.get("type") == "tool_result":
                    tool_errors += bool(content.get("is_error"))
                    if content.get("is_error"):
                        error_tools.append(tool_names.get(content.get("tool_use_id"), "unknown"))
        output = "\n".join(worker_text)
        provenance_free = not re.search(
            r"session[ _-]?id|worker[ _-]?id|actual[ _-]?(?:model|effort)|effort_source|"
            r"summary_ref|STARTUP_SENTINEL|\breceipt\b", output, re.IGNORECASE)
        payload_valid = False
        reporter_valid = False
        try:
            if role == "worklog-reporter":
                reporter_valid = pipeline.parse_worklog(output) == FACTS
                payload_valid = reporter_valid and not worker_tools
            elif writer:
                # Writer system prompts require Markdown implementation summaries.
                # Validate the whole payload and the physical write independently.
                payload_valid = (len(output.encode()) <= 4096 and all(value in output for value in
                                 (sha, f"ROLE_OK:claudex-{role}", "WRITER_OK", "probe-output.txt")))
            else:
                handoff = json.loads(output)
                expected = {"role": role, "candidate_sha": sha, "status": "probe",
                            "marker": f"ROLE_OK:claudex-{role}"}
                if role == "explorer":
                    expected["file_token"] = token
                payload_valid = handoff == expected
        except (ValueError, TypeError):
            pass
        after = None
        try:
            after = pipeline.capture_baseline(repo)
            baseline_preserved = after == baseline
        except ValueError:
            baseline_preserved = False
        writer_delta_valid = (after is not None
                              and all(after[key] == baseline[key] for key in ("head", "branch", "index"))
                              and all(after["inventory"].get(name) == entry
                                      for name, entry in baseline["inventory"].items())
                              and all(name == ".claude/worktrees" or name.startswith(".claude/worktrees/")
                                      for name in after["inventory"].keys() - baseline["inventory"].keys()))
        isolated_files = list((repo / ".claude/worktrees").glob("*/probe-output.txt"))
        writer_file = (len(isolated_files) == 1
                       and isolated_files[0].read_text() == "CLAUDEX_ISOLATED_WRITE\n")
        writer_scope_valid = False
        if writer_file:
            child = isolated_files[0].parent
            writer_scope_valid = (
                not subprocess.check_output(["git", "-C", str(child), "diff", "HEAD", "--raw"], timeout=10)
                and subprocess.check_output(["git", "-C", str(child), "ls-files", "--others",
                                             "--exclude-standard", "-z"], timeout=10) == b"probe-output.txt\0")
        worktrees = subprocess.check_output(["git", "-C", str(repo), "worktree", "list", "--porcelain"], text=True)
        allowed = set(pipeline.dispatcher_tools(root, role)) - {"Agent"}
        dispatcher_valid = (coordinator_tools == ["Agent"] and len(calls) == 1
                            and calls[0]["role"] == f"claudex-{role}"
                            and calls[0]["model_override"] is None
                            and set(worker_tools) <= allowed)
        explorer_valid = role != "explorer" or {"Read", "Glob", "Grep"} <= set(worker_tools)
        writer_valid = (not writer or (writer_file and writer_scope_valid and writer_delta_valid
                                      and worktrees.count("worktree ") == 2
                                      and not (repo / "probe-output.txt").exists()))
        passed = (process.returncode == 0 and tool_errors == 0 and payload_valid
                  and provenance_free and dispatcher_valid and explorer_valid and writer_valid
                  and native_stats.get("spawned") == 1 and native_stats.get("completed") == 1
                  and native_stats.get("failed") == 0 and model in worker_models and worker_models == {model}
                  and (baseline_preserved or writer))
        return {"exit": process.returncode, "role": role, "passed": passed,
                "elapsed_seconds": round(time.monotonic() - started),
                "requested_model": model, "requested_effort": effort,
                "observed_models": sorted(models), "observed_worker_models": sorted(worker_models),
                "actual_effort": None, "effort_source": None, "native_stats": native_stats,
                "discovered_roles": sorted(discovered), "native_calls": [
                    {key: value for key, value in call.items() if key != "id"} for call in calls],
                "tool_errors": tool_errors, "error_tools": error_tools, "dispatcher_valid": dispatcher_valid,
                "output_diagnostics": {"line_count": len(output.splitlines()),
                                       "json_only": output.strip().startswith("{") and output.strip().endswith("}"),
                                       "fenced_json": output.strip().startswith("```json"),
                                       "text_blocks": len(worker_text),
                                       "startup_sentinel": "STARTUP_SENTINEL" in output,
                                       "receipt_word": bool(re.search(r"\breceipt\b", output, re.IGNORECASE))},
                "worker_tools": worker_tools, "role_payload_valid": payload_valid,
                "worker_provenance_absent": provenance_free,
                "explorer_physical_checks": explorer_valid if role == "explorer" else None,
                "reporter_output_valid": reporter_valid if role == "worklog-reporter" else None,
                "reporter_tool_calls": len(worker_tools) if role == "worklog-reporter" else None,
                "baseline_preserved": baseline_preserved, "writer_delta_valid": writer_delta_valid if writer else None,
                "writer_file_isolated": writer_file, "writer_scope_valid": writer_scope_valid if writer else None,
                "main_worktree_untouched": not (repo / "probe-output.txt").exists(),
                "additional_worktree": worktrees.count("worktree ") > 1,
                "fallback": "sol-or-direct" if model.endswith(("-luna", "-terra")) else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--writer", action="store_true")
    parser.add_argument("--role", choices=ROLES, action="append")
    parser.add_argument("--fallback-model", help="exercise a Sol fallback after unconfirmed effort admission")
    args = parser.parse_args()
    selected = args.role or (["builder"] if args.writer else list(ROLES))
    if args.writer and not set(selected) <= {"builder", "reconciliation-builder"}:
        parser.error("writer probes require writer roles")
    if args.fallback_model and (not args.fallback_model.endswith("-sol")
                               or not args.model.endswith(("-luna", "-terra"))):
        parser.error("fallback probe requires an unconfirmed Luna/Terra run and a Sol model")
    probes = []
    for role in selected:
        writer = role in {"builder", "reconciliation-builder"}
        summary = run_probe(args.root.resolve(), args.model, args.effort, args.timeout, role, writer)
        if args.fallback_model:
            admission = subprocess.run([sys.executable, "-I", str(args.root.resolve() / "pipeline.py"),
                                        "select-model", "--model", args.model, "--work-kind", "bounded"],
                                       capture_output=True, timeout=10)
            summary["admission_rejected"] = admission.returncode != 0
            fallback = run_probe(args.root.resolve(), args.fallback_model, "high", args.timeout, role, writer)
            summary["fallback_probe"] = fallback
            summary["passed"] = summary["passed"] and summary["admission_rejected"] and fallback["passed"]
        probes.append(summary)
    result = {"passed": all(probe["passed"] for probe in probes), "probes": probes}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
