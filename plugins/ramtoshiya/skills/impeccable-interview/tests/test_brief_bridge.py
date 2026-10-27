"""Run with IMPECCABLE_TEST_ENGINE set to an installed native Impeccable CLI."""

import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BRIDGE = Path(__file__).resolve().parents[1] / "scripts" / "brief_bridge.py"
TARGET = "src/checkout.tsx"
ALIAS = "route:/checkout"
BEGIN = "<!-- impeccable-interview:start -->"
END = "<!-- impeccable-interview:end -->"
HEADING = "## Interview brief {:#interview-brief}"
DRAFT = "People need to confirm the total before paying.\n"
BLOCK = f"{BEGIN}\n{HEADING}\n\n{DRAFT.rstrip()}\n{END}"


class BriefBridgeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = os.environ.get("IMPECCABLE_TEST_ENGINE")
        if not engine or not Path(engine).is_file() or not os.access(engine, os.X_OK):
            raise RuntimeError(
                "Set IMPECCABLE_TEST_ENGINE to the absolute path of a trusted installed "
                "native Impeccable CLI. This suite does not install an engine."
            )
        cls.engine = str(Path(engine).resolve())

    @contextlib.contextmanager
    def workspace(self):
        with tempfile.TemporaryDirectory(prefix="brief-bridge-test-") as directory:
            self.root = Path(directory).resolve()
            self.project = self.root / "project"
            self.project.mkdir()
            fixtures = {
                "package.json": '{"name":"bridge-fixture","private":true}\n',
                TARGET: "export default function Checkout() { return <button>Pay</button>; }\n",
                "PRODUCT.md": "# Product {:#product}\nConfirm purchases without surprises.\n",
                "DESIGN.md": "# Design {:#design}\nUse the existing blue controls.\n",
                ".impeccable/design.json": '{"fixture":"design-sidecar"}\n',
                ".impeccable/config.json": '{"fixture":"config"}\n',
                ".impeccable/build/receipt.json": '{"fixture":"build"}\n',
                ".impeccable/critique/review.md": "Existing critique, untouched.\n",
            }
            for name, text in fixtures.items():
                path = self.project / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            self.protected = self.snapshot()
            self.draft = self.root / "draft.md"
            self.draft.write_text(DRAFT, encoding="utf-8")
            self.plan = self.root / "plan.json"
            yield
            current = self.snapshot()
            for name, value in self.protected.items():
                self.assertEqual(current.get(name), value, f"Protected fixture changed: {name}")

    def snapshot(self):
        return {
            str(path.relative_to(self.project)): (
                ("link", os.readlink(path)) if path.is_symlink()
                else ("dir",) if path.is_dir() else ("file", path.read_bytes())
            )
            for path in self.project.rglob("*")
        }

    def run_command(self, *args):
        return subprocess.run(
            list(map(str, args)), cwd=self.root, capture_output=True, text=True,
            timeout=45, env={**os.environ, "DO_NOT_TRACK": "1"},
        )

    def successful(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def native(self, *args):
        result = subprocess.run(
            [self.engine, *map(str, args)], cwd=self.project,
            capture_output=True, text=True, timeout=45,
            env={**os.environ, "DO_NOT_TRACK": "1"},
        )
        return self.successful(result)

    def prepare(self, target=TARGET, engine=None, context=None):
        args = [
            sys.executable, "-I", BRIDGE, "prepare", "--project", self.project,
            "--engine", engine or self.engine, "--target", target,
            "--draft", self.draft, "--out", self.plan,
        ]
        if context:
            args += ["--context-file", context]
        return self.run_command(*args)

    def apply(self, approved=True):
        args = [sys.executable, "-I", BRIDGE, "apply", "--plan", self.plan]
        return self.run_command(*args, *(["--approved"] if approved else []))

    def seed(self, body, related=()):
        source = self.root / "surface-body.md"
        source.write_text(body, encoding="utf-8")
        self.native("surface-brief", "write", TARGET, source, *related)
        return self.project / self.native("surface-brief", "path", TARGET).strip()

    def refused_without_writes(self, invoke, reason):
        before = self.snapshot()
        result = invoke()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Refused:", result.stderr)
        self.assertIn(reason, result.stderr)
        self.assertEqual(self.snapshot(), before, result.stdout + result.stderr)

    def test_prepare_save_read_context_reload_and_idempotency(self):
        with self.workspace():
            before = self.snapshot()
            preview = self.successful(self.prepare())
            self.assertEqual(self.snapshot(), before)
            self.assertIn("+" + HEADING, preview)
            self.assertIn(DRAFT.rstrip(), preview)
            saved = json.loads(self.successful(self.apply()))
            self.assertEqual(saved["status"], "saved")
            self.assertEqual(saved["target"], TARGET)
            path = Path(saved["surface_path"])
            readback = self.native("surface-brief", "read", TARGET)
            self.assertEqual(readback.encode(), path.read_bytes())
            self.assertIn(BLOCK, readback)
            context = self.native("context", "--target", TARGET)
            self.assertIn(readback.rstrip(), context)
            self.assertIn(str(path.relative_to(self.project)), context)
            before = self.snapshot()
            self.assertEqual(json.loads(self.successful(self.apply()))["status"], "unchanged")
            self.assertEqual(self.snapshot(), before)
            self.plan.unlink()
            self.successful(self.prepare())
            self.assertEqual(json.loads(self.successful(self.apply()))["status"], "unchanged")
            self.assertEqual(self.snapshot(), before)

    def test_alias_replaces_only_managed_block_and_preserves_related_targets(self):
        with self.workspace():
            prefix = "## Direction contract {:#direction-contract}\n\nTHESIS: Keep the blue checkout.\n\n"
            suffix = "\n\n## Open questions {:#open-questions}\n\nKeep café spacing.  \nKeep this line."
            original = prefix + BLOCK.replace(DRAFT.rstrip(), "Old interview.") + suffix
            path = self.seed(original, (ALIAS, "src/cart.tsx"))
            old = path.read_bytes()
            self.successful(self.prepare(target=ALIAS))
            self.assertEqual(self.snapshot()[str(path.relative_to(self.project))], ("file", old))
            saved = json.loads(self.successful(self.apply()))
            self.assertEqual(saved["target"], TARGET)
            self.assertEqual(Path(saved["surface_path"]), path)
            self.assertEqual(path.read_bytes(), old.replace(b"Old interview.", DRAFT.rstrip().encode()))
            self.assertEqual(len(list(path.parent.glob("*.md"))), 1)
            self.assertEqual(self.native("surface-brief", "read", ALIAS).encode(), path.read_bytes())
            self.assertIn('related_targets: ["route:/checkout","src/cart.tsx"]', path.read_text())

    def test_stale_surface_is_refused(self):
        with self.workspace():
            path = self.seed("Existing strategy.")
            self.successful(self.prepare())
            path.write_bytes(path.read_bytes().replace(b"Existing strategy.", b"Changed strategy."))
            self.refused_without_writes(self.apply, "Surface changed since preparation")

    def test_changed_context_is_refused(self):
        for name in ("PRODUCT.md", "DESIGN.md", "inherited/PRODUCT.md"):
            with self.subTest(context=name), self.workspace():
                external = self.root / "inherited" / "PRODUCT.md"
                external.parent.mkdir()
                external.write_text("Inherited guidance.\n")
                self.successful(self.prepare(context=external))
                path = external if name.startswith("inherited/") else self.project / name
                path.write_bytes(path.read_bytes() + b"Changed after review.\n")
                # The snapshot baseline includes the deliberate context edit.
                if path.is_relative_to(self.project):
                    self.protected[str(path.relative_to(self.project))] = ("file", path.read_bytes())
                expected = path.read_bytes()
                self.refused_without_writes(self.apply, f"Context changed since preparation: {path}")
                self.assertEqual(path.read_bytes(), expected)

    def test_unsupported_metadata_and_unsafe_markers_are_refused(self):
        cases = [
            ("unknown metadata", "Existing strategy.", "Unknown surface metadata", True),
            ("missing end", BEGIN + "\nOld interview.", "Malformed or duplicate interview markers", False),
            ("reversed", END + "\n" + BEGIN, "Malformed or duplicate interview markers", False),
            ("duplicate", BLOCK + "\n" + BLOCK, "Malformed or duplicate interview markers", False),
            ("overlap", BEGIN + "\n## Direction contract\nKeep blue.\n" + END,
             "Interview markers overlap a Direction contract", False),
        ]
        for label, body, reason, metadata in cases:
            with self.subTest(case=label), self.workspace():
                path = self.seed(body)
                if metadata:
                    path.write_bytes(path.read_bytes().replace(b"version: 1\n", b"version: 1\nfuture: true\n"))
                self.refused_without_writes(self.prepare, reason)
                self.assertFalse(self.plan.exists())

    def test_markers_inside_direction_contract_require_canonical_interview_boundary(self):
        with self.workspace():
            self.seed(
                "## Direction contract {:#direction-contract}\n\n"
                "THESIS: Keep checkout.\n\n"
                "<!-- impeccable-interview:start -->\n"
                "FORM: Keep split-pane.\n"
                "FINISH: Keep blue.\n"
                "seed: approved-checkout.png\n"
                "<!-- impeccable-interview:end -->\n\n"
                "## Notes\nKeep notes."
            )
            before = self.snapshot()
            result = self.prepare()
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("Refused:", result.stderr)
            self.assertIn("canonical interview boundary", result.stderr)
            self.assertFalse(self.plan.exists())

    def test_draft_cannot_author_direction_contract(self):
        for heading in ("## Direction contract", "### direction CONTRACT"):
            with self.subTest(heading=heading), self.workspace():
                self.draft.write_text(heading + "\nUse red instead.\n")
                self.refused_without_writes(self.prepare, "The interview cannot author a Direction contract")
                self.assertFalse(self.plan.exists())

    def test_symlink_escape_is_refused(self):
        for kind in ("directory", "brief"):
            with self.subTest(kind=kind), self.workspace():
                outside = self.root / "outside"
                outside.mkdir()
                sentinel = outside / "sentinel.md"
                sentinel.write_text("Outside project.\n")
                if kind == "directory":
                    (self.project / ".impeccable" / "surfaces").symlink_to(outside, target_is_directory=True)
                    reason = "Surface directory escapes the project"
                else:
                    path = self.seed("Existing strategy.")
                    path.unlink()
                    path.symlink_to(sentinel)
                    reason = "Symlinked briefs"
                self.refused_without_writes(self.prepare, reason)
                self.assertEqual(sentinel.read_bytes(), b"Outside project.\n")
                self.assertFalse(self.plan.exists())

    def test_apply_requires_approval(self):
        with self.workspace():
            self.successful(self.prepare())
            self.refused_without_writes(lambda: self.apply(approved=False), "Apply requires --approved")

    def test_unavailable_engine_does_not_install_or_write(self):
        with self.workspace():
            missing = self.root / "not-installed" / "impeccable"
            self.refused_without_writes(
                lambda: self.prepare(engine=missing),
                "Supply an existing project and trusted installed native CLI executable",
            )
            self.assertFalse(missing.parent.exists())
            self.assertFalse(self.plan.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
