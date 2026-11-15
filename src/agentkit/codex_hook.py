"""Codex PreToolUse hook, written out as `.codex/hooks/pre_tool_use.py` and run on its own.

The credential rules are the ones in `hooks/guard_credentials.py`, the reading of a command line
is the one in `hooks/command_line.py`, and the git and delete rules are the ones in
`hooks/guard_git.py`; `tests/test_guards.py` compares the text and runs one command table against
both sides so they cannot drift apart.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

SECRET_PATH = re.compile(
    r"(?:^|[/\\])(?:\.env(?:\.[^/\\]+)?|\.git-credentials|\.netrc|id_rsa|id_ed25519|"
    r"credentials?|secrets?)(?:$|[/\\])",
    re.IGNORECASE,
)
# SECRET_PATH needs a path separator in front of the name, which `cat .env` does not have.
SECRET_FILE_WORD = re.compile(
    r"(?:^|[\s'\"=<>(:,/])(?:\.env(?:\.[\w.-]+)?|\.git-credentials|\.netrc|id_rsa|id_ed25519)"
    r"(?=$|[\s'\")|;&<>,:/])",
    re.IGNORECASE,
)
SECRET_COMMAND = re.compile(
    r"(?:git\s+credential|secret-tool|security\s+find-(?:generic|internet)-password|"
    r"cmdkey\s+/list|Get-StoredCredential|"
    r"(?:Get-ChildItem|gci|dir|ls)\s+Env:|GetEnvironmentVariables)",
    re.IGNORECASE,
)
# `env` or `printenv` as the command itself: at the start of a command, behind a wrapper such as
# `sudo`, or as a whole quoted script. `env NAME=value command` runs a command and prints nothing.
ENV_DUMP = re.compile(
    r"(?:^|[|;&(){`'\"\n])\s*"
    r"(?:(?:sudo|command|exec|time|nohup|xargs)(?:\s+-\S+)*\s+)?"
    r"(?:[\w.-]*/)*"
    r"(?:printenv\b|env(?:\.exe)?(?:\s+(?:-\S+|\w+=\S*))*\s*(?:$|[|;&)}`'\">\n]))",
    re.IGNORECASE,
)
# The whole environment object printed from a one-line script; a single key is not a dump.
SCRIPT_ENV_DUMP = re.compile(
    r"\b(?:node|bun|deno)\b[^\n]*\bprocess\.env\b(?!\s*[.\[])"
    r"|\bpython[\d.]*\b[^\n]*\bos\.environ\b(?!\s*(?:\[|\.get\b))",
    re.IGNORECASE,
)
# Printing a literal word is harmless; the leak is an expanded variable next to a secret name.
TOKEN_ECHO = re.compile(
    r"(?:echo|write-output|write-host|printf)\s+(?=[^\n]*\$)[^\n]*"
    r"(?:token|secret|password|api[_-]?key)",
    re.IGNORECASE,
)
# `<<TAG` expands its body; `<<'TAG'`, `<<"TAG"` and `<<\TAG` take it literally.
HEREDOC_OPERATOR = re.compile(r"<<-?[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|(\\?)([\w.-]+))")
SUBSTITUTION = re.compile(r"\$\([^()]*\)|`[^`]*`")


def _unquoted_heredocs(line: str, quote: str) -> tuple[list[tuple[str, bool]], str]:
    """Heredoc tags opened outside quotes on this line, and the quote state the line ends in."""
    tags: list[tuple[str, bool]] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif line.startswith("<<<", index):
            index += 3
            continue
        elif line.startswith("<<", index):
            match = HEREDOC_OPERATOR.match(line, index)
            if match:
                single, double, escaped, bare = match.groups()
                tags.append((single or double or bare, bare is None or bool(escaped)))
                index = match.end()
                continue
        index += 1
    return tags, quote


def strip_heredoc_bodies(command: str) -> str:
    """Remove heredoc bodies, which are data rather than commands.

    `<<` inside quotes is not a heredoc (`python -c "print(1 << n)"`), and a tag with no closing
    line is not one either; in both cases every following line stays a command. An unquoted tag
    still expands command substitutions, so those are kept and checked.
    """
    lines = command.split("\n")
    kept: list[str] = []
    quote = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        kept.append(line)
        tags, quote = _unquoted_heredocs(line, quote)
        for tag, literal in tags:
            end = next((i for i in range(index, len(lines)) if lines[i].strip() == tag), None)
            if end is None:
                continue
            if not literal:
                for body_line in lines[index:end]:
                    kept.extend(SUBSTITUTION.findall(body_line))
            index = end + 1
    return "\n".join(kept)


def command_reason(raw_command: str) -> str | None:
    command = strip_heredoc_bodies(raw_command)
    normalized = command.replace("\\", "/")
    if SECRET_PATH.search(normalized) or SECRET_FILE_WORD.search(normalized):
        return "agents may not access credential material through a command or patch"
    if (
        SECRET_COMMAND.search(command)
        or ENV_DUMP.search(normalized)
        or SCRIPT_ENV_DUMP.search(command)
    ):
        return "agents may not query credential stores or dump the environment"
    if TOKEN_ECHO.search(command):
        return "agents may not print potential secrets"
    return None


class CommandParseError(ValueError):
    """The command line cannot be read as shell words."""


@dataclass(frozen=True)
class SimpleCommand:
    """One command of a line: its name without folder or `.exe`, in lower case, and its words."""

    name: str
    args: tuple[str, ...]
    # The subshells the command runs in, outermost first; a `cd` holds for its own scope only.
    scope: tuple[int, ...]
    # Behind `xargs`: more arguments arrive on standard input.
    fed: bool = False


# What a substitution leaves behind in the word that held it: a value nobody can know here.
UNKNOWN = "$_"
MAX_DEPTH = 8
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*\+?=")
REDIRECTION = re.compile(r"^(?:\d*|&)(?:>>?|<<?<?|>&|<&|>\|)(.*)$")
KEYWORDS = frozenset({"!", "if", "then", "else", "elif", "do", "while", "until"})
# Commands that run another command, with the options of theirs that take a value.
WRAPPERS: dict[str, frozenset[str]] = {
    "sudo": frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t"}),
    "doas": frozenset({"-u", "-C"}),
    "command": frozenset(),
    "builtin": frozenset(),
    "exec": frozenset({"-a"}),
    "nohup": frozenset(),
    "nice": frozenset({"-n"}),
    "env": frozenset({"-u", "-C"}),
    "time": frozenset({"-f", "-o"}),
    "timeout": frozenset({"-s", "-k"}),
    "xargs": frozenset({"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a"}),
}
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "ash", "fish"})
# Commands of cmd.exe and PowerShell: their paths carry `\`, which is no escape there.
WINDOWS_COMMANDS = frozenset(
    {"rd", "rmdir", "del", "erase", "remove-item", "ri", "cmd", "powershell", "pwsh"}
)


def command_name(word: str) -> str:
    name = re.split(r"[/\\]", word)[-1].lower()
    return name.removesuffix(".exe")


def _groups(brace: str, before: str, following: str, powershell: bool) -> bool:
    """Whether a brace opens or closes a group of commands: not `${x}`, `{a,b}`, `{}` or `@{}`."""
    if brace == "{":
        if before in ("$", "@") or following == "}":
            return False
        return powershell or not following or following.isspace()
    return before != "{" and (powershell or not before or before in "; \t\n")


def _split(
    text: str,
    start: int,
    closer: str,
    powershell: bool,
    scope: tuple[int, ...],
    counter: list[int],
    out: list[tuple[str, tuple[int, ...]]],
) -> int:
    """Cut `text[start:]` into simple commands up to an unquoted `closer`; return where it ended.

    Only the operators are found here; the words of each piece are left to `shlex`.
    """
    current: list[str] = []
    escape = "`" if powershell else "\\"
    quote = ""
    index = start
    size = len(text)

    def flush() -> None:
        piece = "".join(current).strip()
        current.clear()
        if piece:
            out.append((piece, scope))

    def nested(at: int, until: str) -> int:
        counter[0] += 1
        return _split(text, at, until, powershell, (*scope, counter[0]), counter, out)

    while index < size:
        char = text[index]
        following = text[index + 1 : index + 2]
        before = current[-1][-1:] if current else ""
        if quote == "'":
            current.append(char)
            if char == "'":
                quote = ""
            index += 1
            continue
        if char == escape:
            if following != "\n":  # an escaped line end joins two lines
                current.append(text[index : index + 2])
            index += 2
            continue
        if char == "`":
            end = index + 1
            while end < size and text[end] != "`":
                end += 2 if text[end] == "\\" else 1
            if end >= size:
                raise CommandParseError("a backquote is left open")
            counter[0] += 1
            inner = text[index + 1 : end].replace("\\`", "`")
            _split(inner, 0, "", powershell, (*scope, counter[0]), counter, out)
            current.append(UNKNOWN)
            index = end + 1
            continue
        if char == "$" and following == "(":
            index = nested(index + 2, ")")
            current.append(UNKNOWN)
            continue
        if quote:
            current.append(char)
            if char == '"':
                quote = ""
            index += 1
            continue
        if powershell and char == "@" and following and following in "'\"":
            end = text.find(f"\n{following}@", index + 2)
            if end >= 0:  # a here-string is data
                current.append(UNKNOWN)
                index = end + 3
                continue
        if char in "'\"":
            quote = char
            current.append(char)
        elif char == "#" and (not before or before.isspace()):
            while index < size and text[index] != "\n":
                index += 1
            continue
        elif closer and char == closer:
            flush()
            return index + 1
        elif char == "(":
            index = nested(index + 1, ")")
            current.append(UNKNOWN)
            continue
        elif char in ";\n)":
            flush()
        elif char in "|&":
            if (before and before in "<>") or (char == "&" and following == ">"):
                current.append(char)  # `2>&1`, `&>file`, `>|file`
            else:
                flush()
                if following == char:
                    index += 1
        elif char in "{}" and _groups(char, before, following, powershell):
            flush()
        else:
            current.append(char)
        index += 1
    if quote:
        raise CommandParseError("a quote is left open")
    if closer:
        raise CommandParseError("a bracket is left open")
    flush()
    return index


def _words(piece: str, escape: str) -> list[str]:
    lexer = shlex.shlex(piece, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = escape
    try:
        return list(lexer)
    except ValueError as exc:
        raise CommandParseError(str(exc).lower()) from exc


def _without_redirections(words: list[str]) -> list[str]:
    kept: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
            continue
        match = REDIRECTION.match(word)
        if match:
            skip = not match.group(1)
        else:
            kept.append(word)
    return kept


def _unwrap(words: list[str]) -> tuple[list[str], bool]:
    """The command behind assignments, keywords and wrappers, and whether `xargs` feeds it."""
    fed = False
    for _ in range(MAX_DEPTH):
        while words and (words[0] in KEYWORDS or ASSIGNMENT.match(words[0])):
            words = words[1:]
        if not words:
            break
        name = command_name(words[0])
        if name not in WRAPPERS:
            break
        index = 1
        while index < len(words) and words[index].startswith("-") and words[index] != "--":
            if name == "command" and words[index] in ("-v", "-V"):
                return [], fed  # asks where a command is; runs nothing
            index += 2 if words[index] in WRAPPERS[name] else 1
        if index < len(words) and words[index] == "--":
            index += 1
        if name == "timeout":
            index += 1  # the duration
        fed = fed or name == "xargs"
        words = words[index:]
    return words, fed


def _collect(
    text: str, powershell: bool, scope: tuple[int, ...], depth: int
) -> list[SimpleCommand]:
    if depth > MAX_DEPTH:
        raise CommandParseError("commands are nested too deeply")
    counter = [0]
    pieces: list[tuple[str, tuple[int, ...]]] = []
    _split(text, 0, "", powershell, scope, counter, pieces)
    commands: list[SimpleCommand] = []
    for piece, piece_scope in pieces:
        escape = "`" if powershell else "\\"
        words, fed = _unwrap(_without_redirections(_words(piece, escape)))
        if words and not powershell and command_name(words[0]) in WINDOWS_COMMANDS:
            words, fed = _unwrap(_without_redirections(_words(piece, "")))
        if not words:
            continue
        name = command_name(words[0])
        args = words[1:]
        inner = (*piece_scope, -depth - 1)
        if name in SHELLS:
            for position, arg in enumerate(args):
                if not arg.startswith("-") or arg == "--":
                    break
                if not arg.startswith("--") and "c" in arg:
                    script = args[position + 1] if position + 1 < len(args) else ""
                    commands.extend(_collect(script, False, inner, depth + 1))
                    break
        elif name == "eval":
            commands.extend(_collect(" ".join(args), powershell, piece_scope, depth + 1))
        elif name in ("powershell", "pwsh"):
            for position, arg in enumerate(args):
                if len(arg) > 1 and "-command".startswith(arg.lower()):
                    script = " ".join(args[position + 1 :])
                    commands.extend(_collect(script, True, inner, depth + 1))
                    break
        elif name == "cmd":
            for position, arg in enumerate(args):
                if arg.lower() in ("/c", "/k"):
                    script = " ".join(args[position + 1 :])
                    commands.extend(_collect(script, True, inner, depth + 1))
                    break
        commands.append(SimpleCommand(name, tuple(args), piece_scope, fed))
    return commands


def simple_commands(command: str, *, powershell: bool = False) -> list[SimpleCommand]:
    """Every simple command the line runs, in the order the shell reaches them."""
    return _collect(command, powershell, (), 0)


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
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return "hook input must contain a tool_input object"

    candidates: list[Any] = [
        tool_input.get("file_path"),
        tool_input.get("path"),
        tool_input.get("glob"),
        tool_input.get("pattern"),
    ]
    paths = tool_input.get("paths")
    if isinstance(paths, list):
        candidates.extend(paths)
    for candidate in candidates:
        path = str(candidate or "")
        normalized = re.sub(r"[?*{}\[\]]", "", path.replace("\\", "/"))
        if path and SECRET_PATH.search(normalized):
            return f"agents may not read credential material: {path}"

    command = str(tool_input.get("command") or "")
    credential_reason = command_reason(command) if command else None
    if credential_reason:
        return credential_reason
    if not command:
        return None
    cwd = str(data.get("cwd") or os.getcwd())
    # `.codex/hooks/pre_tool_use.py` is two folders below the project root.
    project = str(Path(__file__).resolve().parents[2])
    powershell = str(data.get("tool_name") or "").lower() == "powershell"
    return shell_reason(command, workspace(project, cwd), cwd, powershell)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"BLOCKED: invalid hook input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("BLOCKED: hook input must be a JSON object", file=sys.stderr)
        return 2
    reason = evaluate(data)
    if reason:
        print(f"BLOCKED: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
