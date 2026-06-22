from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from app.git_sync import GitSyncError, git_sync_status, sync_with_git


class GitSyncTests(unittest.TestCase):
    def test_local_mode_refuses_network_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GitSyncError):
                sync_with_git(Path(directory), {"sync_mode": "local"})

    def test_syncs_only_selected_user_data_to_bare_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "library"
            remote = base / "remote.git"
            (root / "papers").mkdir(parents=True)
            (root / "logs/chat_sessions").mkdir(parents=True)
            (root / "originals/papers").mkdir(parents=True)
            (root / "papers/example.yaml").write_text("id: example\nnotes: private note\n")
            (root / "logs/chat_sessions/chat.json").write_text('{"id":"chat"}')
            (root / "originals/papers/example.pdf").write_bytes(b"not-a-real-pdf")
            (root / "unrelated.txt").write_text("must stay local")
            subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                           capture_output=True)

            config = {
                "sync_mode": "git",
                "git_remote": "origin",
                "git_remote_url": str(remote),
                "git_branch": "main",
                "git_sync_chats": True,
                "git_sync_pdfs": False,
            }
            subprocess.run(["git", "init", "-b", "main", str(root)], check=True,
                           capture_output=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "NeuNote Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@neunote.local"], check=True)

            result = sync_with_git(root, config)
            self.assertTrue(result["ok"])
            self.assertEqual(result["pending_files"], 0)
            tracked = subprocess.run(
                ["git", "-C", str(root), "ls-files"], check=True,
                capture_output=True, text=True,
            ).stdout.splitlines()
            self.assertIn("papers/example.yaml", tracked)
            self.assertIn(".gitignore", tracked)
            self.assertIn("logs/chat_sessions/chat.json", tracked)
            self.assertNotIn("originals/papers/example.pdf", tracked)
            self.assertNotIn("unrelated.txt", tracked)
            self.assertTrue(git_sync_status(root, config)["repository"])

            clone_root = base / "second-library"
            (clone_root / "papers").mkdir(parents=True)
            pulled = sync_with_git(clone_root, config)
            self.assertTrue(pulled["ok"])
            self.assertEqual(
                (clone_root / "papers/example.yaml").read_text(),
                "id: example\nnotes: private note\n",
            )

    def test_rejects_library_nested_inside_another_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "library"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(parent)], check=True,
                           capture_output=True)
            config = {
                "sync_mode": "git", "git_remote": "origin",
                "git_remote_url": "unused", "git_branch": "main",
            }
            with self.assertRaisesRegex(GitSyncError, "独立 Git 仓库"):
                sync_with_git(root, config)


if __name__ == "__main__":
    unittest.main()
