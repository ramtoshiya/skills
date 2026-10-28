#!/usr/bin/env python3
"""Bounded native integration probe. Persist summaries only, never stream bodies."""

import argparse
import hashlib
import json
import uuid
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROLES = ("explorer", "builder", "reviewer", "security-reviewer", "runner",
         "reconciliation-builder", "worklog-reporter")


def run_probe(root, model, effort, timeout, prompt):
    command = ["claudex", "--add-dir", str(root), "--model", model,
               "--system-prompt", "You coordinate isolated native capability probes. Follow the supplied probe exactly.",
               "--settings", '{"disableAllHooks":true}',
               "--effort", effort, "--setting-sources", "project", "--strict-mcp-config",
               "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
               "--tools", "Agent,Read,Glob,Grep,Write,Edit", "--allowedTools",
               "Agent,Read,Glob,Grep,Write,Edit", "--permission-mode", "dontAsk",
               "--no-session-persistence", "--output-format", "stream-json",
               "--verbose", "--forward-subagent-text", "-p", prompt]
    environment = os.environ.copy()
    environment["CLAUDE_CODE_SUBAGENT_MODEL"] = model
    # Do not persist stdout/stderr. They may contain native messages or secrets.
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="claudex-probe-") as directory:
        repo = Path(directory)
        subprocess.run(["git", "init", "-q", directory], check=True)
        subprocess.run(["git", "-C", directory, "-c", "user.name=Probe", "-c",
                        "user.email=probe@example.invalid", "commit", "--allow-empty", "-qm", "initial"], check=True)
        sha = subprocess.check_output(["git", "-C", directory, "rev-parse", "HEAD"], text=True).strip()
        issue_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        envelopes = [{"version": 1, "issue_id": issue_id, "attempt_id": attempt_id,
                      "role": role, "base_sha": sha, "candidate_sha": sha,
                      "contract_digest": hashlib.sha256(b"disposable probe").hexdigest(),
                      "cycle": 0, "strategy_change": None, "payload_ref": "probe/payload.md",
                      "evidence_refs": []} for role in ROLES]
        command[-1] = prompt + "\nValidated control envelopes (pass the matching one to each role):\n" + json.dumps(envelopes) + (
            "\nThe inline Markdown payload is the authoritative probe/payload.md for this probe. "
            "No on-disk payload read is required. A probe tests capability, not product acceptance. "
            "Pass the envelope and this payload to each worker in full. Tell each worker to return "
            "a JSON handoff with role, candidate_sha, status=probe, marker=ROLE_OK:claudex-<role>. "
            "Runtime session/model/effort provenance will be added from native evidence by the lead, "
            "not guessed by workers. Use run_in_background=false and wait for completion."
        )
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
            return {"exit": "timeout", "elapsed_seconds": round(time.monotonic() - started),
                    "requested_model": model, "requested_effort": effort, "actual_effort": None,
                    "effort_source": None, "fallback": "sol-or-direct"}
        calls, models, discovered = [], set(), set()
        actual_roles = set()
        worker_models = set()
        native_stats = {}
        writer_evidence = False
        errors = 0
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
                errors += bool(event.get("is_error")) or bool(event.get("permission_denials"))
            message = event.get("message", {})
            actual = message.get("model")
            if isinstance(actual, str) and actual.startswith("gpt-"):
                models.add(actual)
                if event.get("parent_tool_use_id"):
                    worker_models.add(actual)
            for content in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if content.get("type") == "tool_use" and content.get("name") in ("Agent", "Task"):
                    arguments = content.get("input", {})
                    role = arguments.get("subagent_type", "")
                    if role.startswith("claudex-"):
                        calls.append({"role": role, "model_override": arguments.get("model"),
                                      "effort_requested": arguments.get("effort")})
                if content.get("type") == "tool_result":
                    payload = content.get("content", "")
                    body = payload if isinstance(payload, str) else "\n".join(
                        item.get("text", "") for item in payload if isinstance(item, dict))
                    errors += bool(content.get("is_error"))
                    decoder = json.JSONDecoder()
                    for position, character in enumerate(body):
                        if character != "{":
                            continue
                        try:
                            handoff, _ = decoder.raw_decode(body[position:])
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(handoff, dict):
                            continue
                        role = handoff.get("role", "").removeprefix("claudex-")
                        if (role in ROLES and handoff.get("candidate_sha") == sha
                                and handoff.get("status") == "probe"
                                and handoff.get("marker") == f"ROLE_OK:claudex-{role}"):
                            actual_roles.add(f"claudex-{role}")
                    # Only a native tool result can supply this worktree path.
                    if ".claude/worktrees/" in body and "WRITER_OK" in body:
                        writer_evidence = True
        worktrees = subprocess.check_output(["git", "-C", directory, "worktree", "list", "--porcelain"], text=True)
        isolated_files = list((repo / ".claude/worktrees").glob("*/probe-output.txt"))
        writer_file = any(path.read_text() == "CLAUDEX_ISOLATED_WRITE\n" for path in isolated_files)
        return {"exit": process.returncode, "elapsed_seconds": round(time.monotonic() - started),
                "requested_model": model, "requested_effort": effort,
                "observed_models": sorted(models), "observed_worker_models": sorted(worker_models),
                "native_stats": native_stats, "actual_effort": None, "effort_source": None,
                "discovered_roles": sorted(discovered), "native_calls": calls,
                "role_markers": sorted(actual_roles), "tool_errors": errors,
                "writer_native_receipt": writer_evidence, "writer_file_isolated": writer_file,
                "main_worktree_untouched": not (repo / "probe-output.txt").exists(),
                "additional_worktree": worktrees.count("worktree ") > 1,
                "fallback": "sol-or-direct" if model.endswith(("-luna", "-terra")) else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--writer", action="store_true")
    parser.add_argument("--role", choices=ROLES, action="append")
    parser.add_argument("--fallback-model", help="exercise a Sol fallback after unconfirmed effort admission")
    args = parser.parse_args()
    selected = ["builder"] if args.writer else args.role or list(ROLES)
    if args.writer:
        prompt = (
            "This disposable Git repository explicitly authorizes a native worktree probe. "
            "Invoke claudex-builder using the Agent tool, not a top-level --agent. "
            "Pass a bounded probe payload authorizing the builder to create only probe-output.txt "
            "containing exactly CLAUDEX_ISOLATED_WRITE followed by a newline. "
            "The role's native isolation must create the worktree, do not create one yourself. "
            "Ask it to return WRITER_OK and its working directory. Do not edit or read files yourself. "
            "This is an authorized implementation capability probe using the supplied control envelope. "
            "Wait for the worker to finish, then report its native worktree receipt."
        )
    else:
        prompt = (
            "Perform a discovery-only native spawn probe, no product work. "
            "Use the Agent tool to explicitly invoke each of these subagent_type values once: "
            + ", ".join("claudex-" + role for role in selected) + ". "
            "For each supply its control envelope and this bounded Markdown probe payload: discovery-only, "
            "do not inspect files, make no edits, return ROLE_OK:<your exact claudex role name>. "
            "Do not use a generic agent or impersonate roles. Wait for every selected role to finish. "
            "If a role cannot launch report that failure. Do not read or write files yourself."
        )
    summary = run_probe(args.root.resolve(), args.model, args.effort, args.timeout, prompt)
    expected = {"claudex-" + role for role in selected}
    summary["passed"] = (summary["exit"] == 0 and summary.get("tool_errors") == 0
                         and expected <= set(summary.get("role_markers", []))
                         and summary.get("native_stats", {}).get("completed") == len(selected))
    if args.writer:
        summary["passed"] = (summary["passed"] and summary["writer_file_isolated"]
                             and summary["additional_worktree"] and summary["main_worktree_untouched"])
    if args.fallback_model:
        if not args.fallback_model.endswith("-sol") or not summary.get("fallback"):
            parser.error("fallback probe requires an unconfirmed Luna/Terra run and a Sol model")
        admission = subprocess.run([sys.executable, "-I", str(args.root.resolve() / "pipeline.py"),
                                    "select-model", "--model", args.model, "--work-kind", "bounded"],
                                   capture_output=True, timeout=10)
        summary["admission_rejected"] = admission.returncode != 0
        fallback = run_probe(args.root.resolve(), args.fallback_model, "high", args.timeout, prompt)
        summary["fallback_probe"] = fallback
        summary["fallback_passed"] = (fallback["exit"] == 0 and fallback.get("tool_errors") == 0
                                      and expected <= set(fallback.get("role_markers", []))
                                      and args.fallback_model in fallback.get("observed_worker_models", []))
        summary["passed"] = summary["passed"] and summary["admission_rejected"] and summary["fallback_passed"]
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
