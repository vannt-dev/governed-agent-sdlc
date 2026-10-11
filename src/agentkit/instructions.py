"""Find references in agent instruction files that name a file which does not exist.

An agent told to read a file that is gone does not stop: it carries on without that rule, and
nothing reports it. Renaming a role definition or deleting a checklist is enough to cause it, so
`agentkit validate` reports every such reference as a warning.

Only definite references are checked: a path with a directory, or a Markdown link. A bare
file name in prose (`package.json`) usually names a kind of file rather than a location, and
fenced code blocks hold commands and examples.
"""

from __future__ import annotations

import re
from pathlib import Path

from agentkit.config import MANIFEST_NAMES
from agentkit.validator import Finding

INSTRUCTION_GLOBS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/agents/*.md",
    ".claude/skills/**/*.md",
    ".codex/agents/*.toml",
    "core/roles/*.toml",
)
_EXTENSION = r"(?:md|toml|json|ya?ml|py|sh|ps1)"
BACKTICKED = re.compile(rf"`([^`\s]+/[^`\s]*\.{_EXTENSION})`")
LINKED = re.compile(r"\]\(([^)\s]+)\)")
BARE = re.compile(rf"(?<![\w./`*<{{-])((?:[\w.-]+/)+[\w.*-]+\.{_EXTENSION})(?![\w/-])")
PLACEHOLDER = re.compile(r"[<>{}\[\]]|\.\.\.")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")


def instruction_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in INSTRUCTION_GLOBS:
        for file in sorted(root.glob(pattern)):
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for reference in _references(text, markdown=file.suffix.lower() == ".md"):
                if not _exists(root, file, reference):
                    findings.append(
                        Finding(
                            "warning",
                            file,
                            f"Instruction names a file that does not exist: {reference}",
                        )
                    )
    return findings


def _references(text: str, *, markdown: bool) -> list[str]:
    found: dict[str, None] = {}
    in_fence = False
    for line in text.splitlines():
        if markdown and FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        candidates = [*BACKTICKED.findall(line), *BARE.findall(line)]
        if markdown:
            candidates.extend(link.split("#", 1)[0] for link in LINKED.findall(line))
        for candidate in candidates:
            if not candidate or "://" in candidate or candidate.startswith("mailto:"):
                continue
            if PLACEHOLDER.search(candidate):
                continue
            found.setdefault(candidate)
    return list(found)


def _exists(root: Path, file: Path, reference: str) -> bool:
    if reference in MANIFEST_NAMES:
        return any((root / name).is_file() for name in MANIFEST_NAMES)
    if "*" in reference:
        return any(root.glob(reference))
    return (root / reference).exists() or (file.parent / reference).exists()
