import tracemalloc
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
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
