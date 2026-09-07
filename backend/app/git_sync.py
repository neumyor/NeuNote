from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


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
_PROXY_FALLBACK_URL = "socks5h://127.0.0.1:7890"
_REMOTE_PROBE_TIMEOUT_SECONDS = 45
_REMOTE_TRANSFER_TIMEOUT_SECONDS = 3600
_PROXY_REMOTE_TIMEOUT_SECONDS = 3600
_GITHUB_SCP_SSH_URL = re.compile(r"^git@github\.com:(?P<path>[^\s]+)$")
_GITHUB_SSH_URL = re.compile(r"^ssh://git@github\.com(?::\d+)?/(?P<path>[^\s]+)$")


def _run(root: Path, *args: str, check: bool = True, timeout: int = 120,
         env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env_overrides or {})}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], check=False, capture_output=True,
            text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitSyncError("Git 操作超时。请检查网络或远端认证。") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitSyncError(detail or f"Git 命令失败：{' '.join(args)}")
    return result


def _proxy_env() -> dict[str, str] | None:
    """Return per-command proxy settings without changing global Git/SSH config."""
    if shutil.which("nc") is None:
        return None
    return {
        "ALL_PROXY": _PROXY_FALLBACK_URL,
        "all_proxy": _PROXY_FALLBACK_URL,
        "GIT_SSH_COMMAND": (
            'ssh -o BatchMode=yes -o ConnectTimeout=20 '
            '-o ProxyCommand="nc -x 127.0.0.1:7890 -X 5 %h %p"'
        ),
    }


def normalize_remote_url(remote_url: str) -> str:
    """Use GitHub's SSH-over-443 endpoint when an SSH GitHub URL is supplied."""
    remote_url = remote_url.strip()
    scp_match = _GITHUB_SCP_SSH_URL.fullmatch(remote_url)
    if scp_match:
        return f"ssh://git@ssh.github.com:443/{scp_match.group('path')}"
    ssh_match = _GITHUB_SSH_URL.fullmatch(remote_url)
    if ssh_match:
        return f"ssh://git@ssh.github.com:443/{ssh_match.group('path')}"
    return remote_url


def _remote_timeout(args: tuple[str, ...]) -> int:
    return _REMOTE_PROBE_TIMEOUT_SECONDS if args and args[0] == "ls-remote" else _REMOTE_TRANSFER_TIMEOUT_SECONDS


def _remote_detail(result: subprocess.CompletedProcess[str] | None, error: str = "") -> str:
    if error:
        return error
    if result is None:
        return "未知错误"
    return (result.stderr or result.stdout).strip() or f"exit {result.returncode}"


def _run_remote(root: Path, *args: str, check: bool = True,
                transport: dict[str, Any] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a network Git command directly, then retry through local SOCKS5.

    Once a sync has successfully fallen back, subsequent remote commands use the
    proxy directly so a blocked SSH route is not retried for every Git operation.
    """
    transport = transport if transport is not None else {}
    direct_result: subprocess.CompletedProcess[str] | None = None
    direct_error = ""
    if not transport.get("prefer_proxy"):
        try:
            direct_result = _run(root, *args, check=False, timeout=_remote_timeout(args))
        except GitSyncError as exc:
            direct_error = str(exc)
        else:
            if direct_result.returncode == 0:
                return direct_result

    proxy = _proxy_env()
    if proxy is None:
        if check:
            raise GitSyncError(f"Git 远端连接失败：{_remote_detail(direct_result, direct_error)}；未找到 nc，无法通过本机 7890 代理重试。")
        return direct_result or subprocess.CompletedProcess(["git", *args], 1, "", direct_error)
    try:
        proxy_result = _run(
            root, *args, check=False, timeout=_PROXY_REMOTE_TIMEOUT_SECONDS,
            env_overrides=proxy,
        )
    except GitSyncError as exc:
        if check:
            raise GitSyncError(
                f"Git 远端连接失败；直连：{_remote_detail(direct_result, direct_error)}；"
                f"7890 代理：{exc}"
            ) from exc
        return direct_result or subprocess.CompletedProcess(["git", *args], 1, "", str(exc))
    if proxy_result.returncode == 0:
        transport["prefer_proxy"] = True
        transport["proxy_used"] = True
        return proxy_result
    if check:
        raise GitSyncError(
            f"Git 远端连接失败；直连：{_remote_detail(direct_result, direct_error)}；"
            f"7890 代理：{_remote_detail(proxy_result)}"
        )
    return proxy_result


def _validate(remote: str, branch: str) -> None:
    if not _SAFE_REMOTE.fullmatch(remote):
        raise GitSyncError("Git remote 名称无效。")
    if not _SAFE_REF.fullmatch(branch) or branch.startswith(("-", "/")) or ".." in branch:
        raise GitSyncError("Git 分支名称无效。")


def sync_paths(config: dict[str, Any]) -> list[str]:
    paths = [".gitignore", "papers", "assets/paper_figures"]
    if config.get("git_sync_chats"):
        paths.append("logs/chat_sessions")
    if config.get("git_sync_pdfs"):
        paths.append("originals/papers")
    return paths


def sync_inventory(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Summarize sync coverage and broken paper asset references."""
    paper_files = sorted((root / "papers").glob("*.yaml"))
    pdf_refs: list[str] = []
    figure_refs: list[str] = []
    invalid_papers: list[str] = []
    for path in paper_files:
        try:
            paper = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            invalid_papers.append(path.name)
            continue
        source = paper.get("source_pdf")
        if isinstance(source, str) and source:
            pdf_refs.append(source)
        for figure in paper.get("key_figures") or []:
            image_path = figure.get("image_path") if isinstance(figure, dict) else None
            if isinstance(image_path, str) and image_path:
                figure_refs.append(image_path)

    missing_pdfs = sorted({path for path in pdf_refs if not (root / path).is_file()})
    missing_figures = sorted({path for path in figure_refs if not (root / path).is_file()})
    return {
        "paper_records": len(paper_files),
        "pdf_files": sum(1 for path in (root / "originals/papers").glob("*") if path.is_file()),
        "figure_files": sum(1 for path in (root / "assets/paper_figures").glob("*") if path.is_file()),
        "chat_sessions": sum(1 for path in (root / "logs/chat_sessions").glob("*.json") if path.is_file()),
        "pdf_sync_enabled": bool(config.get("git_sync_pdfs")),
        "chat_sync_enabled": bool(config.get("git_sync_chats")),
        "invalid_papers": invalid_papers,
        "missing_pdf_references": missing_pdfs,
        "missing_figure_references": missing_figures,
        "complete": not invalid_papers and not missing_pdfs and not missing_figures,
    }


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


def _ensure_local_git_identity(root: Path) -> None:
    """Set repo-local identity when the user's global Git identity is absent."""
    name = _run(root, "config", "--get", "user.name", check=False).stdout.strip()
    email = _run(root, "config", "--get", "user.email", check=False).stdout.strip()
    if not name:
        _run(root, "config", "user.name", "NeuNote Sync")
    if not email:
        _run(root, "config", "user.email", "neunote-sync@local")


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
        "inventory": sync_inventory(root, config),
    }


def _is_path_tracked(root: Path, path: str) -> bool:
    return bool(_run(root, "ls-files", "--", path, check=False).stdout.strip())


def _remove_disabled_optional_data(root: Path, config: dict[str, Any]) -> None:
    """Remove disabled private data from Git while retaining local files."""
    disabled = []
    if not config.get("git_sync_chats"):
        disabled.append("logs/chat_sessions")
    if not config.get("git_sync_pdfs"):
        disabled.append("originals/papers")
    for path in disabled:
        if _is_path_tracked(root, path):
            _run(root, "rm", "-r", "--cached", "--ignore-unmatch", "--", path)


def _pull_rebase_or_recover(root: Path, remote: str, branch: str,
                            transport: dict[str, Any]) -> None:
    result = _run_remote(
        root, "pull", "--rebase", "--autostash", remote, branch,
        check=False, transport=transport,
    )
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout).strip()
    git_dir = root / ".git"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        _run(root, "rebase", "--abort", check=False)
    raise GitSyncError(
        "远端与本地数据发生冲突，已自动恢复到同步前状态。"
        "请检查冲突论文后重试。" + (f" Git: {detail}" if detail else "")
    )


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
    remote_url = normalize_remote_url(str(config.get("git_remote_url") or ""))
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
    _ensure_local_git_identity(root)

    existing_remote = _run(root, "remote", "get-url", remote, check=False)
    if existing_remote.returncode != 0:
        if not remote_url:
            raise GitSyncError(f"未找到远端 {remote}，请填写远端仓库 URL。")
        _run(root, "remote", "add", remote, remote_url)
    elif remote_url and existing_remote.stdout.strip() != remote_url:
        _run(root, "remote", "set-url", remote, remote_url)

    # Remote Git commands first use the normal system route.  If it is
    # unavailable, the rest of this sync stays on the local 7890 proxy route.
    transport: dict[str, Any] = {}
    remote_ref = f"refs/heads/{branch}"
    remote_has_branch = _run_remote(
        root, "ls-remote", "--exit-code", "--heads", remote, remote_ref,
        check=False, transport=transport,
    ).returncode == 0
    has_head = _run(root, "rev-parse", "--verify", "HEAD", check=False).returncode == 0
    bootstrapped_from_remote = remote_has_branch and not has_head
    if bootstrapped_from_remote:
        # Knowledge-base sync only needs the current data snapshot. Fetching an
        # entire PDF-heavy history on a new device can be prohibitively slow.
        _run_remote(root, "fetch", "--depth=1", remote, branch, transport=transport)
        _run(root, "checkout", "-B", branch, "FETCH_HEAD")

    _ensure_data_gitignore(root)
    paths = sync_paths(config)
    _remove_disabled_optional_data(root, config)
    add_paths = [path for path in paths if (root / path).exists() or _is_path_tracked(root, path)]
    _run(root, "add", "-A", "-f", "--", *add_paths)
    committed = False
    if _run(root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        _run(root, "commit", "-m", f"Sync NeuNote user data ({stamp})")
        committed = True

    if remote_has_branch and not bootstrapped_from_remote:
        _pull_rebase_or_recover(root, remote, branch, transport)
    _run_remote(root, "push", "-u", remote, branch, transport=transport)

    result = git_sync_status(root, config)
    result.update({"ok": True, "initialized": initialized, "committed": committed,
                   "inventory": sync_inventory(root, config),
                   "proxy_fallback_used": bool(transport.get("proxy_used")),
                   "message": (
                       "用户数据已通过本机 7890 代理同步到 Git 远端。"
                       if transport.get("proxy_used")
                       else "用户数据已同步到 Git 远端。"
                   )})
    return result
