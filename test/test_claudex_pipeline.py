import tracemalloc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "setup/agents/claudex-pipeline"
spec = importlib.util.spec_from_file_location("pipeline", SOURCE / "pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def control():
    return {
        "version": 1, "issue_id": str(uuid.uuid4()), "attempt_id": str(uuid.uuid4()),
        "role": "builder", "base_sha": "a" * 40, "candidate_sha": "b" * 40,
        "contract_digest": hashlib.sha256(b"contract").hexdigest(), "cycle": 0,
        "strategy_change": None, "payload_ref": "attempts/payload.md", "evidence_refs": [],
    }


def receipt():
    record = control()
    return {key: record[key] for key in ("version", "issue_id", "attempt_id", "role", "candidate_sha")} | {
        "session_id": str(uuid.uuid4()), "worker_id": "a123456789abcdef0", "actual_model": "gpt-6.1-sol",
        "actual_effort": None, "effort_source": None, "status": "probe",
        "evidence_refs": [], "summary_ref": "attempts/summary.md",
    }


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.destination = self.root / "installed"

    def test_install_update_retire_and_conflicts(self):
        source = self.root / "source"
        shutil.copytree(SOURCE, source)
        pipeline.reconcile(source, self.destination, "install")
        pipeline.reconcile(source, self.destination, "status")
        manifest = self.destination / pipeline.MANIFEST
        original_mtime = manifest.stat().st_mtime_ns
        pipeline.reconcile(source, self.destination, "install")
        self.assertEqual(manifest.stat().st_mtime_ns, original_mtime)
        unrelated = self.destination / "personal.md"
        unrelated.write_text("keep me")
        role = ".claude/agents/claudex-builder.md"
        (source / role).write_text((source / role).read_text() + "\nNew guidance.\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            pipeline.reconcile(source, self.destination, "status")
        pipeline.reconcile(source, self.destination, "install")
        self.assertIn("New guidance", (self.destination / role).read_text())
        (self.destination / role).write_text("personal customization")
        for operation in ("install", "uninstall", "status"):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "local conflict"):
                pipeline.reconcile(source, self.destination, operation)
        self.assertTrue(manifest.exists())
        (self.destination / role).write_bytes((source / role).read_bytes())
        pipeline.reconcile(source, self.destination, "uninstall")
        pipeline.reconcile(source, self.destination, "uninstall")
        self.assertEqual(unrelated.read_text(), "keep me")
        self.assertFalse(manifest.exists())
        pipeline.reconcile(source, self.destination, "install")
        pipeline.reconcile(source, self.destination, "status")

    def test_unowned_different_file_and_symlink_are_preserved(self):
        self.destination.mkdir()
        external = self.root / "external"
        external.write_text("keep")
        for symlink in (False, True):
            path = self.destination / "pipeline.py"
            if symlink:
                path.symlink_to(external)
            else:
                path.write_text("keep")
            with self.assertRaises(ValueError):
                pipeline.reconcile(SOURCE, self.destination, "install")
            self.assertEqual(path.read_text(), "keep")
            self.assertFalse((self.destination / pipeline.MANIFEST).exists())
            path.unlink()
        self.assertEqual(external.read_text(), "keep")

    def test_symlink_above_destination_cannot_redirect_install_or_uninstall(self):
        external = self.root / "external"
        external.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(external, target_is_directory=True)
        destination = alias / "installed"
        for operation in ("install", "status", "uninstall"):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "symlink"):
                pipeline.reconcile(SOURCE, destination, operation)
        self.assertEqual(list(external.iterdir()), [])

    def test_oversized_control_rejection_has_bounded_memory_use(self):
        path = self.root / "large.json"
        path.write_bytes(b" " * (4 * 1024 * 1024))
        tracemalloc.start()
        try:
            with self.assertRaisesRegex(ValueError, "limit"):
                pipeline.read_json(path)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)

    def test_role_capability_and_output_contract(self):
        pipeline.validate_package(SOURCE)
        source = self.root / "source"
        shutil.copytree(SOURCE, source)
        path = source / ".claude/agents/claudex-reviewer.md"
        path.write_text(path.read_text().replace('["Read", "Glob", "Grep"]', '["Read", "Glob", "Grep", "Bash"]'))
        with self.assertRaisesRegex(ValueError, "capability"):
            pipeline.validate_package(source)

    def test_reporter_output_rejects_every_extra_or_missing_field(self):
        valid = (
            "- Completed work: Checked the package.\n"
            "- Current activity: Reviewing results.\n"
            "- Next step: Run verification.\n"
            "- Blocker: None.\n"
        )
        self.assertEqual(pipeline.parse_worklog(valid)["blocker"], "None.")
        invalid = [
            valid + "## Evidence\n", "Here is the worklog.\n" + valid,
            valid + '{"version": 1}\n', "```markdown\n" + valid + "```\n",
            valid + "STARTUP_SENTINEL\n", valid.replace("- Blocker: None.\n", ""),
            valid + "- Blocker: Unknown.\n", valid.replace("None.", ""),
            valid.replace("None.", "<!-- hidden receipt -->"),
            valid.replace("None.", '{"status":"probe"}'),
            valid.replace("None.", "STARTUP_SENTINEL"),
            valid.replace("None.", "session_id=123"),
            valid.replace("None.", "gpt-6.1-sol effort high"),
            valid.replace("None.", "None.\x00hidden"),
            valid.replace("None.", "None.​hidden"),
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                pipeline.parse_worklog(text)
        draft = self.root / "draft.md"
        for text, expected in ((valid, 0), (valid + "PRIVATE_STARTUP_SENTINEL\n", 1)):
            draft.write_text(text)
            result = subprocess.run([sys.executable, "-I", str(SOURCE / "pipeline.py"),
                                     "validate-worklog", "--file", str(draft)], capture_output=True, text=True)
            self.assertEqual(result.returncode, expected)
            self.assertNotIn("PRIVATE_STARTUP_SENTINEL", result.stdout + result.stderr)

    def test_runtime_baseline_preservation_and_clean_preflight(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
        git("init", "-q")
        tracked = repo / "product.txt"
        tracked.write_text("original\n")
        git("add", "product.txt")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial")
        runtime = {".claude/settings.json": "{}", ".multica/context.json": "{}", "CLAUDE.md": "runtime\n"}
        for name, body in runtime.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        (repo / ".git/info/exclude").write_text(".multica/\n")
        baseline = pipeline.capture_baseline(repo)
        pipeline.verify_baseline(repo, baseline)
        record = self.root / "baseline.json"
        command = [sys.executable, "-I", str(SOURCE / "pipeline.py")]
        for operation in ("capture-baseline", "verify-baseline"):
            result = subprocess.run(command + [operation, "--repo", str(repo), "--file", str(record)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(pipeline.read_json(record), baseline)
        result = subprocess.run(command + ["capture-baseline", "--repo", str(repo), "--file", str(record)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(pipeline.read_json(record), baseline)
        self.assertEqual(set(baseline["runtime_paths"]), set(runtime) | {".claude", ".multica"})
        for mutation in ("addition", "empty-directory", "removal", "content", "mode", "index", "tracked", "branch", "head", "worktree"):
            with self.subTest(mutation=mutation):
                path = repo / ".multica/context.json"
                if mutation == "addition":
                    (repo / ".claude/new.md").write_text("new")
                elif mutation == "empty-directory":
                    (repo / ".claude/empty").mkdir()
                elif mutation == "mode":
                    path.chmod(0o755)
                elif mutation == "head":
                    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "next")
                elif mutation == "worktree":
                    git("worktree", "add", "-q", "--detach", str(self.root / "extra"))
                elif mutation == "removal":
                    path.unlink()
                elif mutation == "content":
                    path.write_text("changed")
                elif mutation == "index":
                    git("add", "CLAUDE.md")
                elif mutation == "tracked":
                    tracked.write_text("changed\n")
                else:
                    git("checkout", "-qb", "other")
                with self.assertRaises(ValueError):
                    pipeline.verify_baseline(repo, baseline)
                if mutation == "addition":
                    (repo / ".claude/new.md").unlink()
                elif mutation == "empty-directory":
                    (repo / ".claude/empty").rmdir()
                elif mutation == "mode":
                    path.chmod(0o644)
                elif mutation == "head":
                    git("reset", "--soft", baseline["head"])
                elif mutation == "worktree":
                    git("worktree", "remove", str(self.root / "extra"))
                elif mutation == "index":
                    git("reset", "-q", "HEAD", "--", "CLAUDE.md")
                elif mutation == "tracked":
                    tracked.write_text("original\n")
                elif mutation == "branch":
                    git("checkout", "-q", baseline["branch"])
                else:
                    path.write_text("{}")
                pipeline.verify_baseline(repo, baseline)
        (repo / "unexpected.txt").write_text("product")
        with self.assertRaisesRegex(ValueError, "unexpected untracked"):
            pipeline.capture_baseline(repo)
        (repo / "unexpected.txt").unlink()
        tracked.write_text("dirty\n")
        with self.assertRaisesRegex(ValueError, "tracked/index"):
            pipeline.capture_baseline(repo)
        git("add", "product.txt")
        with self.assertRaisesRegex(ValueError, "tracked/index"):
            pipeline.capture_baseline(repo)

    def clean_repo(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args, input=None):
            return subprocess.check_output(["git", "-C", str(repo), *args],
                                           input=input, text=True).strip()
        git("init", "-q")
        (repo / "product.txt").write_text("original\n")
        git("add", "product.txt")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial")
        return repo, git

    def test_instruction_free_repository_and_large_baseline_cli(self):
        repo, git = self.clean_repo()
        for name in ("AGENTS.md", "CLAUDE.md", "AGENTS.local.md", "CLAUDE.local.md", ".worktreeinclude"):
            self.assertFalse((repo / name).exists())
        for index in range(83):
            (repo / f"product-{index:03}-{'x' * 26}.txt").write_text("product\n")
        git("add", ".")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "inventory")
        (repo / ".claude").mkdir()
        for index in range(21):
            (repo / ".claude" / f"runtime-{index:03}-{'y' * 45}.json").write_text("{}")
        record = self.root / "baseline.json"
        command = [sys.executable, "-I", str(SOURCE / "pipeline.py")]
        def run(operation):
            return subprocess.run(command + [operation, "--repo", str(repo), "--file", str(record)],
                                  capture_output=True, text=True)
        result = run("capture-baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        baseline = json.loads(record.read_bytes())
        self.assertEqual(len(baseline["index"]), 84)
        self.assertEqual(len(baseline["inventory"]), 106)
        formatted = json.dumps(baseline, indent=2, sort_keys=True)
        self.assertGreater(len(formatted.encode()), 32768)
        self.assertLess(record.stat().st_size, len(formatted.encode()))
        for data in (record.read_text(), formatted):
            record.write_text(data)
            result = run("verify-baseline")
            self.assertEqual(result.returncode, 0, result.stderr)
        baseline["index"][0]["flags"] ^= 0x8000
        record.write_text(json.dumps(baseline))
        result = run("verify-baseline")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("baseline changed", result.stderr)
        for data in ("{malformed", " " * (pipeline.BASELINE_LIMIT + 1)):
            record.write_text(data)
            self.assertNotEqual(run("verify-baseline").returncode, 0)
        for index in range(pipeline.BASELINE_ENTRIES):
            (repo / ".claude" / f"extra-{index}").touch()
        record.unlink()
        result = run("capture-baseline")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inventory exceeds limit", result.stderr)
        self.assertFalse(record.exists())

    def test_baseline_ignores_stat_cache_and_index_encoding_refresh(self):
        repo, git = self.clean_repo()
        baseline = pipeline.capture_baseline(repo)
        index = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index"))
        before = index.read_bytes()
        path = repo / "product.txt"
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        git("update-index", "--refresh")
        self.assertNotEqual(index.read_bytes(), before, "fixture must change raw index bytes")
        pipeline.verify_baseline(repo, baseline)
        git("update-index", "--index-version=4")
        git("write-tree")
        pipeline.verify_baseline(repo, baseline)
        for invalid in (baseline | {"version": 1}, baseline | {"version": True}, [], None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "version"):
                pipeline.verify_baseline(repo, invalid)

    def test_semantic_index_detects_staging_conflicts_and_persistent_flags(self):
        repo, git = self.clean_repo()
        baseline = pipeline.capture_baseline(repo)
        index = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index"))
        original = index.read_bytes()
        oid = git("rev-parse", "HEAD:product.txt")
        changed = git("hash-object", "-w", "--stdin", input="changed\n")
        mutations = {
            "addition": ("update-index", "--add", "--cacheinfo", "100644", oid, "staged.txt"),
            "deletion": ("update-index", "--force-remove", "product.txt"),
            "mode": ("update-index", "--cacheinfo", "100755", oid, "product.txt"),
            "object": ("update-index", "--cacheinfo", "100644", changed, "product.txt"),
            "assume-unchanged": ("update-index", "--assume-unchanged", "product.txt"),
            "skip-worktree": ("update-index", "--skip-worktree", "product.txt"),
            "intent-to-add": ("add", "--intent-to-add", "new.txt"),
            "conflict-stages": ("update-index", "--index-info"),
        }
        for name, arguments in mutations.items():
            with self.subTest(mutation=name):
                if name == "intent-to-add":
                    (repo / "new.txt").write_text("new\n")
                conflict = (f"0 {'0' * 40}\tproduct.txt\n"
                            + "".join(f"100644 {oid if stage != 3 else changed} {stage}\tproduct.txt\n"
                                      for stage in (1, 2, 3)))
                git(*arguments, input=conflict if name == "conflict-stages" else None)
                actual = pipeline.semantic_index(repo)
                self.assertNotEqual(actual, baseline["index"])
                if name == "conflict-stages":
                    self.assertEqual([entry["stage"] for entry in actual], [1, 2, 3])
                if name == "intent-to-add":
                    entry = next(entry for entry in actual if entry["path"] == "new.txt")
                    self.assertEqual(entry["flags"], 0x20000000)
                if name in ("assume-unchanged", "skip-worktree"):
                    self.assertEqual(git("status", "--porcelain"), "")
                with self.assertRaises(ValueError):
                    pipeline.verify_baseline(repo, baseline)
                index.write_bytes(original)
                (repo / "new.txt").unlink(missing_ok=True)
                pipeline.verify_baseline(repo, baseline)

    def test_runtime_baseline_rejects_inventory_and_content_overflow(self):
        repo, _ = self.clean_repo()
        runtime = repo / ".multica"
        runtime.mkdir()
        large = runtime / "large"
        with large.open("wb") as stream:
            stream.truncate(32 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, "content exceeds limit"):
            pipeline.capture_baseline(repo)
        large.unlink()
        for number in range(2049):
            (runtime / str(number)).mkdir()
        with self.assertRaisesRegex(ValueError, "inventory exceeds limit"):
            pipeline.capture_baseline(repo)

    def test_fingerprint_exclusions_and_installed_ownership_conflicts(self):
        source = self.root / "source"
        shutil.copytree(SOURCE, source)
        before = pipeline.package_fingerprint(source)
        for name in ("__pycache__/cached.pyc", ".DS_Store", ".git/config", ".in_use", "extra.pyc"):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("excluded")
        self.assertEqual(pipeline.package_fingerprint(source), before)
        pipeline.reconcile(source, self.destination, "install")
        self.assertEqual(pipeline.package_fingerprint(self.destination), before)
        owned = self.destination / "pipeline.py"
        original = owned.read_bytes()
        owned.write_bytes(original + b"\n# local edit\n")
        with self.assertRaisesRegex(ValueError, "local conflict"):
            pipeline.package_fingerprint(self.destination)
        owned.write_bytes(original)
        for name in ("unexpected.txt", "pipeline.py"):
            path = self.destination / name
            if path.exists():
                path.unlink()
            path.symlink_to(source / "pipeline.py")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "symlink"):
                pipeline.package_fingerprint(self.destination)
            path.unlink()
            if name == "pipeline.py":
                path.write_bytes(original)
        (self.destination / "unexpected.txt").write_text("unowned")
        with self.assertRaisesRegex(ValueError, "unexpected package content"):
            pipeline.package_fingerprint(self.destination)
        (self.destination / "unexpected.txt").unlink()
        manifest = self.destination / pipeline.MANIFEST
        value = json.loads(manifest.read_text())
        value["files"]["pipeline.py"] = "0" * 64
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "local conflict"):
            pipeline.package_fingerprint(self.destination)

    def test_dispatcher_cli_and_every_role_payload_boundary(self):
        for role in sorted(pipeline.ROLES):
            with self.subTest(role=role):
                expected = ["Agent"]
                if role != "worklog-reporter":
                    expected += ["Read", "Glob", "Grep"]
                if role in pipeline.WRITERS:
                    expected += ["Edit", "Write"]
                result = subprocess.run([sys.executable, "-I", str(SOURCE / "pipeline.py"),
                                         "dispatcher-tools", "--role", role], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip().split(","), expected)
                _, body = pipeline.role_definition(SOURCE, role)
                output = body.split("## Output {:#output}")[1]
                self.assertNotRegex(output, r"(?i)(?:include|return)\s+(?:a\s+)?(?:v1\s+)?receipt\b")
                self.assertIn("The lead assembles and validates receipts", output)

    def test_control_rejects_invalid_provenance_and_repair_cycles(self):
        pipeline.validate_control(control())
        bad_values = {
            "version": [True, 2], "role": ["lead"], "candidate_sha": ["main"],
            "issue_id": ["not-a-uuid"], "cycle": [True, -1, 4, 3],
            "evidence_refs": [["../../secret"], ["https://user:secret@example.org"]],
            "payload_ref": ["/tmp/payload", "token=secret"],
        }
        for field, values in bad_values.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError)):
                    pipeline.validate_control(control() | {field: value})
        pipeline.validate_control(control() | {"cycle": 3, "strategy_change": "approach"})
        with self.assertRaises(ValueError):
            pipeline.validate_control(control() | {"transcript": "secret"})

    def test_selection_fails_closed_for_unconfirmed_luna_and_terra(self):
        pipeline.admit_model("gpt-6.1-sol")
        for model in ("gpt-6-luna", "gpt-6.1-terra"):
            for evidence in (None, receipt(), receipt() | {"actual_model": model}):
                with self.subTest(model=model), self.assertRaises(ValueError):
                    pipeline.admit_model(model, evidence)
            trusted = receipt() | {"actual_model": model, "actual_effort": "max", "effort_source": "native/invocation-1"}
            self.assertEqual(pipeline.admit_model(model, trusted), model)
        for effort in ("off", "minimal", "low"):
            luna = receipt() | {"actual_model": "gpt-6-luna", "actual_effort": effort,
                                "effort_source": "native/invocation-1"}
            self.assertEqual(pipeline.admit_model("gpt-6-luna", luna, "bounded"), "gpt-6-luna")
            with self.assertRaises(ValueError):
                pipeline.admit_model("gpt-6-luna", luna, "reasoning")
            with self.assertRaises(ValueError):
                pipeline.admit_model("gpt-6.1-terra", luna | {"actual_model": "gpt-6.1-terra"}, "bounded")
        with self.assertRaises(ValueError):
            pipeline.validate_receipt(receipt() | {"actual_effort": "max"})

    def test_receipt_binding_rejects_stale_or_cross_attempt_evidence(self):
        envelope = control()
        record = receipt() | {key: envelope[key] for key in
                              ("issue_id", "attempt_id", "role", "candidate_sha")}
        pipeline.validate_receipt(record, envelope)
        pipeline.validate_receipt(record | {"actual_model": None}, envelope)
        for field, value in (("issue_id", str(uuid.uuid4())), ("attempt_id", str(uuid.uuid4())),
                             ("role", "reviewer"), ("candidate_sha", "c" * 40)):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "mismatched"):
                pipeline.validate_receipt(record | {field: value}, envelope)

    def test_recovery_shared_across_worktrees_and_bounded_to_issue(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
        git("init", "-q")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "initial")
        sha = git("rev-parse", "HEAD")
        worktree = self.root / "worktree"
        git("worktree", "add", "-q", "--detach", str(worktree))
        record = {"version": 1, "control": control() | {"base_sha": sha, "candidate_sha": sha},
                  "receipt_refs": ["attempts/receipt.json"], "blocker": None}
        path = pipeline.save_active(repo, record)
        self.assertEqual(path, pipeline.save_active(worktree, record))
        self.assertEqual(json.loads(path.read_text()), record)
        self.assertEqual(path.parts[-2], record["control"]["issue_id"])
        record["control"]["candidate_sha"] = "f" * 40
        with self.assertRaises(subprocess.CalledProcessError):
            pipeline.save_active(repo, record)
        self.assertEqual(json.loads(path.read_text())["control"]["candidate_sha"], sha)

    def test_cli_does_not_echo_rejected_secret_body(self):
        bad = self.root / "bad.json"
        bad.write_text(json.dumps(control() | {"raw_transcript": "SECRET_SENTINEL"}))
        result = subprocess.run([shutil.which("python3") or "python3", "-I", str(SOURCE / "pipeline.py"),
                                 "validate-control", "--file", str(bad)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SECRET_SENTINEL", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
