"""Tests for the public repository export tool."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Add project root to path for imports
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.export_public_repo import (
    load_manifest,
    resolve_include_paths,
    collect_allowlisted_files,
    should_deny_file,
    scan_content_leakage,
    export_public_repo,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "configs" / "public_export_manifest.json"


class TestManifestLoading(unittest.TestCase):
    """Test manifest parsing and validation."""

    def test_load_valid_manifest(self):
        manifest = load_manifest(MANIFEST_PATH)
        self.assertIn("target", manifest)
        self.assertIn("include", manifest)
        self.assertIn("overlay", manifest)
        self.assertIn("deny_names", manifest)
        self.assertIn("deny_prefixes", manifest)
        self.assertIn("deny_content_regex", manifest)

    def test_load_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_manifest(Path("/nonexistent/manifest.json"))

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json")
            f.flush()
            try:
                with self.assertRaises(json.JSONDecodeError):
                    load_manifest(Path(f.name))
            finally:
                os.unlink(f.name)


class TestDenyRules(unittest.TestCase):
    """Test deny pattern matching."""

    def test_deny_agent_files(self):
        self.assertTrue(should_deny_file("AGENTS.md", ["AGENTS.md", "CLAUDE.md"], []))
        self.assertTrue(should_deny_file("CLAUDE.md", ["AGENTS.md", "CLAUDE.md"], []))

    def test_deny_prefixes(self):
        self.assertTrue(should_deny_file(".claude/settings.json", [], [".claude/"]))
        self.assertTrue(should_deny_file(".codegraph/index.db", [], [".codegraph/"]))
        self.assertTrue(should_deny_file("outputs/test/image.png", [], ["outputs/"]))

    def test_allow_normal_files(self):
        self.assertFalse(should_deny_file("src/image_factory/models.py", [], []))
        self.assertFalse(should_deny_file("tests/test_export.py", [], []))
        self.assertFalse(should_deny_file("pyproject.toml", [], []))


class TestContentLeakage(unittest.TestCase):
    """Test content leakage scanning."""

    def test_detect_volume_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("path = '/Volumes/ExternalDrive/data'\n")
            f.flush()
            try:
                violations = scan_content_leakage(
                    Path(f.name), ["/Volumes/"]
                )
                self.assertEqual(len(violations), 1)
                self.assertIn("/Volumes/", violations[0][2])
            finally:
                os.unlink(f.name)

    def test_detect_user_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            private_path = "/" + "Users/private-user/projects"
            private_pattern = "/" + "Users/private-user/"
            f.write(f"home = '{private_path}'\n")
            f.flush()
            try:
                violations = scan_content_leakage(
                    Path(f.name), [private_pattern]
                )
                self.assertEqual(len(violations), 1)
            finally:
                os.unlink(f.name)

    def test_detect_api_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("OPENAI_API_KEY=sk-abc123def456\n")
            f.flush()
            try:
                violations = scan_content_leakage(
                    Path(f.name), ["OPENAI_API_KEY=sk-"]
                )
                self.assertEqual(len(violations), 1)
            finally:
                os.unlink(f.name)

    def test_no_violation_on_clean_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nprint('hello')\n")
            f.flush()
            try:
                violations = scan_content_leakage(
                    Path(f.name), ["/Volumes/", "/Users/example-user/"]
                )
                self.assertEqual(len(violations), 0)
            finally:
                os.unlink(f.name)


class TestExportGitPreservation(unittest.TestCase):
    """Test that .git/ directory is preserved during export."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.target = Path(self.tmpdir) / "export_target"
        self.target.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_git_dir_preserved_after_export(self):
        # Create a fake .git directory in target
        git_dir = self.target / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (git_dir / "config").write_text("[core]\n\tbare = false\n")

        # Run export
        export_public_repo(MANIFEST_PATH, target_override=self.target)

        # Verify .git is preserved
        self.assertTrue(git_dir.exists())
        self.assertTrue((git_dir / "HEAD").exists())
        self.assertTrue((git_dir / "config").exists())

    def test_git_dir_not_created_if_missing(self):
        # Run export without pre-existing .git
        export_public_repo(MANIFEST_PATH, target_override=self.target)

        # Verify .git was not created
        self.assertFalse((self.target / ".git").exists())


class TestStaleFileCleanup(unittest.TestCase):
    """Test that stale files are removed during export."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.target = Path(self.tmpdir) / "export_target"
        self.target.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_stale_file_removed(self):
        # Create a stale file that shouldn't be in the export
        stale_file = self.target / "old_file.txt"
        stale_file.write_text("should be removed")

        # Run export
        export_public_repo(MANIFEST_PATH, target_override=self.target)

        # Verify stale file was removed
        self.assertFalse(stale_file.exists())

    def test_allowed_file_kept(self):
        # Run export first to create allowed files
        export_public_repo(MANIFEST_PATH, target_override=self.target)

        # Verify at least one allowed file exists
        pyproject = self.target / "pyproject.toml"
        self.assertTrue(pyproject.exists())


class TestExportWithTempTarget(unittest.TestCase):
    """Test full export flow with temporary target."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.target = Path(self.tmpdir) / "public_export"

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_full_export_creates_files(self):
        exit_code = export_public_repo(
            MANIFEST_PATH, target_override=self.target
        )
        self.assertEqual(exit_code, 0)

        # Verify key files exist
        self.assertTrue((self.target / "pyproject.toml").exists())
        self.assertTrue((self.target / "src" / "image_factory" / "__init__.py").exists())

    def test_export_excludes_deny_prefixes(self):
        exit_code = export_public_repo(
            MANIFEST_PATH, target_override=self.target
        )
        self.assertEqual(exit_code, 0)

        # Verify denied paths don't exist
        self.assertFalse((self.target / ".claude").exists())
        self.assertFalse((self.target / ".codegraph").exists())
        self.assertFalse((self.target / "AGENTS.md").exists())
        self.assertFalse((self.target / "CLAUDE.md").exists())

    def test_check_mode_reports_no_drift_on_fresh(self):
        # First export
        export_public_repo(MANIFEST_PATH, target_override=self.target)

        # Then check - should report up to date
        exit_code = export_public_repo(
            MANIFEST_PATH, target_override=self.target, check_only=True
        )
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
