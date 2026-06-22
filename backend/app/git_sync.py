from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class GitSyncError(RuntimeError):
    pass


_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")
_SAFE_REMOTE = re.compile(r"^[A-Za-z0-9._-]+$")

DATA_GITIGNORE = """\
# NeuNote machine-local configuration and operational data
AGENT.md
metadata/
logs/
originals/
*.DS_Store
"""

_SYNC_LOCK = threading.Lock()


def _run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], check=False, capture_output=True,
            text=True, timeout=120, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitSyncError("Git 操作超时。请检查网络或远端认证。") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitSyncError(detail or f"Git 命令失败：{' '.join(args)}")
    return result


def _validate(remote: str, branch: str) -> None:
    if not _SAFE_REMOTE.fullmatch(remote):
        raise GitSyncError("Git remote 名称无效。")
    if not _SAFE_REF.fullmatch(branch) or branch.startswith(("-", "/")) or ".." in branch:
        raise GitSyncError("Git 分支名称无效。")


def sync_paths(config: dict[str, Any]) -> list[str]:
    paths = [".gitignore", "papers"]
    if config.get("git_sync_chats"):
        paths.append("logs/chat_sessions")
    if config.get("git_sync_pdfs"):
        paths.append("originals/papers")
    return paths


def _is_repo(root: Path) -> bool:
    return _repo_root(root) is not None


def _repo_root(root: Path) -> Path | None:
    result = _run(root, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _ensure_data_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    if not path.exists():
        path.write_text(DATA_GITIGNORE, encoding="utf-8")


def git_sync_status(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    enabled = config.get("sync_mode") == "git"
    paths = sync_paths(config)
    if not enabled:
        return {"enabled": False, "available": shutil.which("git") is not None,
                "repository": False, "paths": paths, "detail": "当前为仅本地模式。"}
    if shutil.which("git") is None:
        return {"enabled": enabled, "available": False, "repository": False,
                "paths": paths, "detail": "系统未安装 Git。"}
    repo_root = _repo_root(root)
    if repo_root is None:
        return {"enabled": enabled, "available": True, "repository": False,
                "paths": paths, "detail": "尚未初始化 Git 仓库。首次同步时会自动初始化。"}
    if repo_root != root.resolve():
        return {"enabled": enabled, "available": True, "repository": False,
                "paths": paths, "separate_repository": False,
                "detail": "知识库位于代码或其他 Git 仓库内，请先选择独立的数据目录。"}

    branch = _run(root, "branch", "--show-current", check=False).stdout.strip()
    remote = str(config.get("git_remote") or "origin")
    remote_result = _run(root, "remote", "get-url", remote, check=False)
    status = _run(root, "status", "--porcelain", "--ignored", "--", *paths,
                  check=False).stdout
    pending = len([line for line in status.splitlines() if line.strip()])
    last_commit = _run(root, "log", "-1", "--format=%h %s", check=False).stdout.strip()
    return {
        "enabled": enabled, "available": True, "repository": True,
        "branch": branch, "remote": remote,
        "remote_configured": remote_result.returncode == 0,
        "pending_files": pending, "paths": paths, "last_commit": last_commit,
        "detail": "Git 同步已启用。" if enabled else "当前为仅本地模式。",
    }


def sync_with_git(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    if not _SYNC_LOCK.acquire(blocking=False):
        raise GitSyncError("另一个 Git 同步任务正在运行，请稍后再试。")
    try:
        return _sync_with_git_unlocked(root, config)
    finally:
        _SYNC_LOCK.release()


def _sync_with_git_unlocked(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    if config.get("sync_mode") != "git":
        raise GitSyncError("当前为仅本地模式，请先在设置中启用 Git 同步。")
    if shutil.which("git") is None:
        raise GitSyncError("系统未安装 Git。")

    remote = str(config.get("git_remote") or "origin").strip()
    branch = str(config.get("git_branch") or "main").strip()
    remote_url = str(config.get("git_remote_url") or "").strip()
    _validate(remote, branch)

    initialized = False
    repo_root = _repo_root(root)
    if repo_root is not None and repo_root != root.resolve():
        raise GitSyncError("知识库必须使用独立 Git 仓库，不能位于 NeuNote 代码仓库或其他仓库内。")
    if repo_root is None:
        if not remote_url:
            raise GitSyncError("首次 Git 同步需要填写远端仓库 URL。")
        _run(root, "init", "-b", branch)
        initialized = True

    current_branch = _run(root, "branch", "--show-current").stdout.strip()
    if not current_branch:
        _run(root, "checkout", "-b", branch)
        current_branch = branch
    if current_branch != branch:
        raise GitSyncError(f"当前仓库位于 {current_branch} 分支，与配置的 {branch} 不一致。")

    existing_remote = _run(root, "remote", "get-url", remote, check=False)
    if existing_remote.returncode != 0:
        if not remote_url:
            raise GitSyncError(f"未找到远端 {remote}，请填写远端仓库 URL。")
        _run(root, "remote", "add", remote, remote_url)
    elif remote_url and existing_remote.stdout.strip() != remote_url:
        _run(root, "remote", "set-url", remote, remote_url)

    remote_ref = f"refs/heads/{branch}"
    remote_has_branch = _run(root, "ls-remote", "--exit-code", "--heads", remote,
                             remote_ref, check=False).returncode == 0
    has_head = _run(root, "rev-parse", "--verify", "HEAD", check=False).returncode == 0
    if remote_has_branch and not has_head:
        _run(root, "fetch", remote, branch)
        _run(root, "checkout", "-B", branch, "FETCH_HEAD")

    _ensure_data_gitignore(root)
    paths = sync_paths(config)
    _run(root, "add", "-A", "-f", "--", *paths)
    committed = False
    if _run(root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        _run(root, "commit", "-m", f"Sync NeuNote user data ({stamp})")
        committed = True

    if remote_has_branch:
        _run(root, "pull", "--rebase", "--autostash", remote, branch)
    _run(root, "push", "-u", remote, branch)

    result = git_sync_status(root, config)
    result.update({"ok": True, "initialized": initialized, "committed": committed,
                   "message": "用户数据已同步到 Git 远端。"})
    return result
