#!/usr/bin/env python
"""PreToolUse guard: no force push, no push to a protected branch, no destructive git or delete.

The command line is read by `command_line.py`, so a rule fires on a command that runs and not on
text that names one: `git commit -m "never git push --force"` passes, while `git status && git
push --force`, `bash -c "git reset --hard"` and `FOO=1 sudo rm -rf /` are refused. Heredoc bodies
are data.

A protected branch is matched by name (`main`, `master`, `develop`) in every refspec form:
`origin main`, `HEAD:main`, `x:refs/heads/main`, and a deletion (`:main`). A default branch with
another name is not covered.

A recursive delete (`rm -r`, `rm -rf`, `rm -R`, `rm --recursive`, `rd /s`, `del /s`,
`Remove-Item -Recurse`) is refused unless every target is a named path inside the workspace.
Refused: `/`, `~`, `$HOME`, `.`, `..`, a bare `*`, the workspace or the current folder itself, a
path outside the workspace, anything in a `.git` folder, and a target the text does not tell (a
variable, a substitution, arguments from `xargs`). `rm -rf build` and `rm -rf build/*` pass. An
agent's shell has no terminal, so `rm -r` without `-f` asks nothing and counts the same. Paths are
compared as text: a symbolic link is not followed. The workspace is the project the guard lives
in, or the repository around the working directory when that lies elsewhere (a separate worktree).

A command line that cannot be read (a quote or bracket left open) is refused when it names git or
a delete command, because then nothing in it can be checked.

`src/agentkit/codex_hook.py` carries the same rules for Codex; `tests/test_guards.py` runs one
command table against both.
"""

from __future__ import annotations

import os
import re
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from command_line import CommandParseError, SimpleCommand, simple_commands
from common import deny, input_error, read_hook_input, tool_input, tool_input_error
from guard_credentials import strip_heredoc_bodies

PROTECTED_REF = re.compile(r"^\+?(?:[^:]*:)?(?:refs/heads/)?(?:main|master|develop)$", re.I)
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
DESTRUCTIVE_GIT = "destructive git commands require an explicit human-approved workflow"
# A line that cannot be read is refused only when one of these is in it.
GUARDED_WORD = re.compile(r"(?<![\w-])(?:git|rm|rd|rmdir|del|erase|ri|remove-item)(?![\w-])", re.I)
DELETE_COMMANDS = frozenset({"rm", "rd", "rmdir", "del", "erase", "remove-item", "ri"})
CHANGE_FOLDER = frozenset({"cd", "chdir", "pushd", "popd", "set-location", "sl"})
# Parameters of PowerShell's Remove-Item, which `rm` is an alias of there; a prefix is enough.
POWERSHELL_PARAMETERS = (
    "-force",
    "-path",
    "-literalpath",
    "-erroraction",
    "-confirm",
    "-whatif",
    "-verbose",
    "-include",
    "-exclude",
    "-filter",
)
HOME_WORDS = ("~", "$HOME", "${HOME}", "$env:USERPROFILE", "$env:HOME")
PATH_SEPARATOR = re.compile(r"[/\\]")
EVERYTHING = re.compile(r"^(?:\*+|\.\*)$")


def _short_flag(args: tuple[str, ...], letter: str) -> bool:
    return any(a.startswith("-") and not a.startswith("--") and letter in a for a in args)


def git_reason(args: tuple[str, ...]) -> str | None:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in GIT_VALUE_OPTIONS else 1
    if index >= len(args):
        return None
    subcommand, rest = args[index].lower(), args[index + 1 :]
    if subcommand == "push":
        forced = _short_flag(rest, "f") or any(a.startswith("--force") for a in rest)
        if forced or any(a.startswith("+") for a in rest):
            return "force push is forbidden"
        if any(PROTECTED_REF.match(a) for a in rest if not a.startswith("-")):
            return "push through a task branch and pull request, not directly to a protected branch"
    elif subcommand == "reset":
        if "--hard" in rest:
            return DESTRUCTIVE_GIT
    elif subcommand == "clean":
        if _short_flag(rest, "f") or "--force" in rest:
            return DESTRUCTIVE_GIT
    elif subcommand == "checkout" and "--" in rest[:-1]:
        return DESTRUCTIVE_GIT
    return None


def _parameter(arg: str, names: tuple[str, ...], shortest: int) -> bool:
    word = arg.lower().split(":")[0]
    return len(word) >= shortest and any(name.startswith(word) for name in names)


def recursive_delete_targets(command: SimpleCommand) -> list[str] | None:
    """What a recursive delete names, or None when the command is not one."""
    posix = command.name == "rm"
    recursive = False
    literal = False
    targets: list[str] = []
    for arg in command.args:
        if literal or len(arg) == 1 or not arg.startswith(("-", "/")):
            targets.append(arg)
        elif arg == "--":
            literal = True
        elif arg.startswith("/"):
            if posix or not re.fullmatch(r"/[A-Za-z?]", arg):
                targets.append(arg)
            elif arg.lower() == "/s":
                recursive = True
        elif arg == "--recursive" or _parameter(arg, ("-recurse",), 2):
            recursive = True
        elif posix and not arg.startswith("--") and not _parameter(arg, POWERSHELL_PARAMETERS, 3):
            recursive = recursive or "r" in arg.lower()  # `-rf`, `-fR`, `-vr`
    return targets if recursive else None


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("/\\") + os.sep)


def locate(target: str, cwd: str | None) -> str | None:
    """The absolute path a word names, from the text alone; None when the text does not say."""
    for home in HOME_WORDS:
        if target == home or target.startswith((home + "/", home + "\\")):
            target = os.path.expanduser("~") + target[len(home) :]
            break
    else:
        if target.startswith("~"):
            return None
    if cwd and (target == "$PWD" or target.startswith(("$PWD/", "$PWD\\"))):
        target = cwd + target[4:]
    if any(char in target for char in "$`%") or ("{" in target and "," in target):
        return None
    if os.name == "nt":  # `/c/work` is how Git Bash writes `C:/work`
        target = re.sub(r"^/([A-Za-z])(?=/|$)", r"\1:", target)
        if re.fullmatch(r"[A-Za-z]:", target):
            target += "/"
    else:  # PowerShell and cmd.exe paths use `\` between folders on every system
        target = target.replace("\\", "/")
    if cwd is None and not os.path.isabs(target):
        return None
    return os.path.normcase(os.path.abspath(os.path.join(cwd or "", target)))


def target_reason(target: str, root: str, cwd: str | None) -> str | None:
    """Why a recursive delete of `target` is refused, or None for a named path in the workspace."""
    parts = [part for part in PATH_SEPARATOR.split(target) if part]
    for part in parts:
        name = part.lower()
        wild = name.startswith(".") and any(char in name for char in "*?[")
        if name == ".git" or (wild and fnmatchcase(".git", name)):
            return "it reaches a .git folder"
    path = target
    if parts and EVERYTHING.match(parts[-1]):  # everything in a folder: judge the folder
        path = target[: target.rstrip("/\\").rfind(parts[-1])] or "."
    where = locate(path, cwd)
    if where is None:
        return "the command line does not tell what it deletes"
    if not _inside(where, root):
        return "it is outside the workspace"
    if where == root:
        return "it is the workspace itself"
    if cwd is not None and _inside(os.path.normcase(cwd), where):
        return "it is the current folder or one above it"
    return None


class Folders:
    """Where each subshell of a command line stands, as far as its `cd` commands tell."""

    def __init__(self, cwd: str) -> None:
        self.current: dict[tuple[int, ...], str | None] = {(): cwd}
        self.stack: list[str | None] = []

    def of(self, scope: tuple[int, ...]) -> str | None:
        for length in range(len(scope), -1, -1):
            if scope[:length] in self.current:
                return self.current[scope[:length]]
        return None

    def move(self, command: SimpleCommand) -> None:
        here = self.of(command.scope)
        if command.name == "popd":
            self.current[command.scope] = self.stack.pop() if self.stack else None
            return
        if command.name == "pushd":
            self.stack.append(here)
        targets = [arg for arg in command.args if arg == "-" or not arg.startswith("-")]
        target = targets[0] if targets else "~"
        self.current[command.scope] = None if target == "-" else locate(target, here)


def shell_reason(command: str, root: str, cwd: str, powershell: bool = False) -> str | None:
    """Why the git and delete rules refuse a command line, or None when they do not."""
    try:
        commands = simple_commands(strip_heredoc_bodies(command), powershell=powershell)
    except CommandParseError as exc:
        if GUARDED_WORD.search(command):
            return f"the command line cannot be read ({exc}), so it cannot be checked"
        return None
    root = os.path.normcase(os.path.abspath(root))
    folders = Folders(os.path.abspath(cwd))
    for item in commands:
        if item.name == "git":
            reason = git_reason(item.args)
            if reason:
                return reason
        elif item.name in CHANGE_FOLDER:
            folders.move(item)
        elif item.name in DELETE_COMMANDS:
            targets = recursive_delete_targets(item)
            if targets is None:
                continue
            if item.fed:
                return "recursive delete refused: xargs hands it targets that cannot be checked"
            for target in targets:
                why = target_reason(target, root, folders.of(item.scope))
                if why:
                    return (
                        f"recursive delete of {target} refused: {why}; "
                        "delete a named path inside the workspace"
                    )
    return None


def workspace(project: str, cwd: str) -> str:
    """The project the guard lives in, or the repository around a working directory elsewhere."""
    here = os.path.abspath(cwd)
    if _inside(os.path.normcase(here), os.path.normcase(os.path.abspath(project))):
        return project
    folder = here
    while True:
        if os.path.exists(os.path.join(folder, ".git")):
            return folder
        parent = os.path.dirname(folder)
        if parent == folder:
            return here
        folder = parent


def evaluate(data: dict[str, Any]) -> str | None:
    malformed = input_error(data)
    if malformed:
        return malformed
    malformed_tool = tool_input_error(data)
    if malformed_tool:
        return malformed_tool
    command = str(tool_input(data).get("command") or "")
    if not command:
        return None
    cwd = str(data.get("cwd") or os.getcwd())
    project = str(Path(__file__).resolve().parents[1])
    powershell = str(data.get("tool_name") or "").lower() == "powershell"
    return shell_reason(command, workspace(project, cwd), cwd, powershell)


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
