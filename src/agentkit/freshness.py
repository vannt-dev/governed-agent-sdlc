"""Content fingerprints, never source text, bind evidence to the reviewed inputs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

IGNORED = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".junto",
}


def _ignored(path: str) -> bool:
    parts = Path(path).parts
    return (
        any(part in IGNORED for part in parts)
        or Path(path).name.startswith(".coverage")
        or _evidence_or_environment(path)
    )


def _evidence_or_environment(path: str) -> bool:
    return (
        Path(path).name == ".env"
        or Path(path).name.startswith(".env.")
        or path.startswith((".agent/runs/", ".junto/", "docs/agent/reviews/", "docs/agent/qa/"))
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, timeout=30, check=False
    )


def capture_source(
    root: Path, refs: dict[str, str | None] | None = None, background: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    refs = refs or {}
    git = _git(root, "rev-parse", "--show-toplevel")
    paths: set[str] = set()
    tracked: set[str] = set()
    head: str | None = None
    index: str | None = None
    resolved_refs: dict[str, str] = {}
    if git.returncode == 0:
        if Path(git.stdout.decode().strip()).resolve() != root:
            raise ValueError("Review root must be the Git repository root")
        listing = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if listing.returncode:
            raise ValueError("Cannot enumerate source for review fingerprint")
        paths.update(p for p in listing.stdout.decode("utf-8").split("\0") if p)
        revision = _git(root, "rev-parse", "--verify", "HEAD")
        head = revision.stdout.decode().strip() if revision.returncode == 0 else None
        staged = _git(root, "ls-files", "--stage", "-z")
        if staged.returncode:
            raise ValueError("Cannot fingerprint the Git index")
        index = digest(staged.stdout)
        tracked.update(
            entry.split("\t", 1)[1]
            for entry in staged.stdout.decode("utf-8").split("\0")
            if "\t" in entry
        )
        for name, ref in refs.items():
            if ref:
                revision = _git(
                    root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
                )
                if revision.returncode:
                    raise ValueError(f"Cannot resolve review ref: {name}")
                resolved_refs[name] = revision.stdout.decode().strip()
    else:
        if (root / ".git").exists() or any(refs.values()):
            raise ValueError("Cannot resolve Git source for review fingerprint")
        # Mock/local workflows may precede git init; exclude generated evidence and tool state.
        for directory, folders, filenames in os.walk(root):
            folders[:] = [
                f
                for f in folders
                if not _ignored((Path(directory) / f).relative_to(root).as_posix() + "/")
            ]
            paths.update(
                (Path(directory) / file).relative_to(root).as_posix() for file in filenames
            )
    files: dict[str, str] = {}
    modes: dict[str, int] = {}
    for relative in sorted(paths):
        if _evidence_or_environment(relative) or (relative not in tracked and _ignored(relative)):
            continue
        path = root / relative
        if path.exists() or path.is_symlink():
            modes[relative] = path.lstat().st_mode
        if path.is_symlink():
            files[relative] = digest(os.readlink(path).encode())
        elif path.is_file():
            path.resolve().relative_to(root)
            with path.open("rb") as handle:
                hasher = hashlib.sha256()
                while chunk := handle.read(65536):
                    hasher.update(chunk)
            files[relative] = hasher.hexdigest()
        elif not path.exists():
            files[relative] = "deleted"
        else:
            raise ValueError(f"Cannot fingerprint source directory/submodule: {relative}")
    result: dict[str, Any] = {
        "version": 1,
        "head": head,
        "index": index,
        "refs": refs,
        "resolvedRefs": resolved_refs,
        "files": files,
        "modes": modes,
        "background": digest(background.read_bytes())
        if background and background.is_file()
        else None,
    }
    result["fingerprint"] = digest(json.dumps(result, sort_keys=True).encode())
    return result


def source_is_current(root: Path, run_dir: Path, recorded: dict[str, Any]) -> bool:
    if recorded.get("version") != 1 or not isinstance(recorded.get("refs"), dict):
        return False
    current = capture_source(root, recorded["refs"], run_dir / "review-background.md")
    return bool(current["fingerprint"] == recorded.get("fingerprint"))
