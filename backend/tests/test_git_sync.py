from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.git_sync import (
    GitSyncError,
    _run_remote,
    _remote_timeout,
    git_sync_status,
    normalize_remote_url,
    sync_inventory,
    sync_with_git,
)


class GitSyncTests(unittest.TestCase):
    def test_normalizes_github_ssh_urls_to_port_443(self) -> None:
        self.assertEqual(
            normalize_remote_url("git@github.com:owner/library.git"),
            "ssh://git@ssh.github.com:443/owner/library.git",
        )
        self.assertEqual(
            normalize_remote_url("ssh://git@github.com:22/owner/library.git"),
            "ssh://git@ssh.github.com:443/owner/library.git",
        )
        self.assertEqual(
            normalize_remote_url("https://github.com/owner/library.git"),
            "https://github.com/owner/library.git",
        )

    def test_remote_transfer_timeout_allows_large_initial_sync(self) -> None:
        self.assertEqual(_remote_timeout(("ls-remote", "origin")), 45)
        self.assertEqual(_remote_timeout(("fetch", "origin", "main")), 3600)
        self.assertEqual(_remote_timeout(("push", "origin", "main")), 3600)

    def test_remote_command_uses_direct_route_when_available(self) -> None:
        result = subprocess.CompletedProcess(["git"], 0, "ok", "")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("app.git_sync._run", return_value=result) as run, \
                    mock.patch("app.git_sync._proxy_env") as proxy_env:
                transport: dict[str, object] = {}
                actual = _run_remote(Path(directory), "push", "origin", "main",
                                     transport=transport)

        self.assertIs(actual, result)
        run.assert_called_once()
        proxy_env.assert_not_called()
        self.assertNotIn("proxy_used", transport)

    def test_remote_command_falls_back_to_local_7890_proxy(self) -> None:
        direct = subprocess.CompletedProcess(["git"], 1, "", "network unreachable")
        proxied = subprocess.CompletedProcess(["git"], 0, "", "")
        proxy = {"ALL_PROXY": "socks5h://127.0.0.1:7890"}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("app.git_sync._run", side_effect=[direct, proxied]) as run, \
                    mock.patch("app.git_sync._proxy_env", return_value=proxy):
                transport: dict[str, object] = {}
                actual = _run_remote(Path(directory), "push", "origin", "main",
                                     transport=transport)

        self.assertIs(actual, proxied)
        self.assertTrue(transport["proxy_used"])
        self.assertTrue(transport["prefer_proxy"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].kwargs["env_overrides"], proxy)

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
            (root / "assets/paper_figures").mkdir(parents=True)
            (root / "logs/chat_sessions").mkdir(parents=True)
            (root / "originals/papers").mkdir(parents=True)
            (root / "papers/example.yaml").write_text("id: example\nnotes: private note\n")
            (root / "assets/paper_figures/example_figure_1_p3.png").write_bytes(b"png")
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
            self.assertIn("assets/paper_figures/example_figure_1_p3.png", tracked)
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
            self.assertEqual(
                (clone_root / "assets/paper_figures/example_figure_1_p3.png").read_bytes(),
                b"png",
            )

    def test_first_sync_sets_repo_local_identity_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "library"
            remote = base / "remote.git"
            fake_home = base / "home"
            (root / "papers").mkdir(parents=True)
            fake_home.mkdir()
            (root / "papers/example.yaml").write_text("id: example\n")
            subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                           capture_output=True)

            config = {
                "sync_mode": "git",
                "git_remote": "origin",
                "git_remote_url": str(remote),
                "git_branch": "main",
            }
            with mock.patch.dict("os.environ", {"HOME": str(fake_home)}, clear=False):
                result = sync_with_git(root, config)

            self.assertTrue(result["ok"])
            self.assertEqual(
                subprocess.run(["git", "-C", str(root), "config", "--get", "user.name"],
                               check=True, capture_output=True, text=True).stdout.strip(),
                "NeuNote Sync",
            )
            self.assertEqual(
                subprocess.run(["git", "-C", str(root), "config", "--get", "user.email"],
                               check=True, capture_output=True, text=True).stdout.strip(),
                "neunote-sync@local",
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

    def test_pdf_opt_in_and_later_disable_removes_remote_copy_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "library"
            remote = base / "remote.git"
            (root / "papers").mkdir(parents=True)
            (root / "originals/papers").mkdir(parents=True)
            (root / "papers/example.yaml").write_text(
                "id: example\nsource_pdf: originals/papers/example.pdf\n"
            )
            pdf = root / "originals/papers/example.pdf"
            pdf.write_bytes(b"pdf")
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            config = {
                "sync_mode": "git", "git_remote": "origin",
                "git_remote_url": str(remote), "git_branch": "main",
                "git_sync_pdfs": True,
            }

            sync_with_git(root, config)
            self.assertIn(
                "originals/papers/example.pdf",
                subprocess.run(
                    ["git", "-C", str(root), "ls-files"], check=True,
                    capture_output=True, text=True,
                ).stdout.splitlines(),
            )

            config["git_sync_pdfs"] = False
            sync_with_git(root, config)
            self.assertTrue(pdf.exists())
            self.assertNotIn(
                "originals/papers/example.pdf",
                subprocess.run(
                    ["git", "-C", str(root), "ls-files"], check=True,
                    capture_output=True, text=True,
                ).stdout.splitlines(),
            )

    def test_inventory_reports_missing_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "papers").mkdir()
            (root / "papers/example.yaml").write_text(
                "id: example\n"
                "source_pdf: originals/papers/missing.pdf\n"
                "key_figures:\n  - image_path: assets/paper_figures/missing.png\n"
            )
            inventory = sync_inventory(root, {"git_sync_pdfs": True})
            self.assertFalse(inventory["complete"])
            self.assertEqual(inventory["missing_pdf_references"], ["originals/papers/missing.pdf"])
            self.assertEqual(inventory["missing_figure_references"], ["assets/paper_figures/missing.png"])


if __name__ == "__main__":
    unittest.main()
