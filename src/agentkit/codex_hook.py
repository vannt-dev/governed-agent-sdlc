"""Codex PreToolUse hook, written out as `.codex/hooks/pre_tool_use.py` and run on its own.

The credential rules are the ones in `hooks/guard_credentials.py`, the reading of a command line
is the one in `hooks/command_line.py`, the git and delete rules are the ones in
`hooks/guard_git.py`, and the rules on sending data out are the ones in `hooks/guard_egress.py`;
`tests/test_guards.py` and `tests/test_egress.py` compare the text and run one command table
against both sides so they cannot drift apart.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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


# A line that cannot be read is refused only when one of these is in it.
EGRESS_WORD = re.compile(
    r"(?<![\w-])(?:curl|wget|scp|rsync|nc|ncat|netcat|invoke-webrequest|iwr|"
    r"invoke-restmethod|irm)(?![\w-])",
    re.I,
)
EGRESS_HINT = "add the host to [egress] allowed_hosts in the manifest if it is trusted"
MANIFEST_NAMES = ("agentkit.toml", ".agent/project.toml")
# The options of each command that take a value, so a value is not read as a destination. An
# option missing here is taken to have none: its value then counts as one more destination,
# which can only refuse more, never less.
CURL_SHORT_VALUES = frozenset("AbcCdDeEFHKmoPQrtTuUwxXyYz")
CURL_LONG_VALUES = frozenset(
    {
        "abstract-unix-socket",
        "aws-sigv4",
        "cacert",
        "capath",
        "cert",
        "cert-type",
        "ciphers",
        "config",
        "connect-timeout",
        "connect-to",
        "continue-at",
        "cookie",
        "cookie-jar",
        "data",
        "data-ascii",
        "data-binary",
        "data-raw",
        "data-urlencode",
        "dns-servers",
        "dump-header",
        "expand-data",
        "expand-data-binary",
        "expand-data-urlencode",
        "expand-json",
        "expand-url",
        "form",
        "form-string",
        "ftp-port",
        "header",
        "interface",
        "json",
        "keepalive-time",
        "key",
        "key-type",
        "limit-rate",
        "local-port",
        "max-filesize",
        "max-redirs",
        "max-time",
        "noproxy",
        "oauth2-bearer",
        "output",
        "output-dir",
        "pass",
        "pinnedpubkey",
        "proto",
        "proto-default",
        "proto-redir",
        "proxy",
        "proxy-header",
        "proxy-user",
        "quote",
        "range",
        "referer",
        "request",
        "resolve",
        "retry",
        "retry-delay",
        "retry-max-time",
        "speed-limit",
        "speed-time",
        "telnet-option",
        "time-cond",
        "trace",
        "trace-ascii",
        "unix-socket",
        "upload-file",
        "url",
        "user",
        "user-agent",
        "variable",
        "write-out",
    }
)
# A body read from a file when the value starts with `@`.
CURL_AT_FILE = frozenset(
    {"d", "data", "data-ascii", "data-binary", "json", "expand-data", "expand-data-binary"}
)
CURL_AT_FILE_NAMED = frozenset({"data-urlencode", "expand-data-urlencode", "variable"})
WGET_SHORT_VALUES = frozenset("aAbBDeiIlOoPQRtTUwX")
WGET_LONG_VALUES = frozenset(
    {
        "accept",
        "append-output",
        "base",
        "bind-address",
        "body-data",
        "body-file",
        "ca-certificate",
        "certificate",
        "directory-prefix",
        "domains",
        "exclude-directories",
        "exclude-domains",
        "execute",
        "header",
        "http-password",
        "http-user",
        "include-directories",
        "input-file",
        "level",
        "limit-rate",
        "load-cookies",
        "method",
        "output-document",
        "output-file",
        "password",
        "post-data",
        "post-file",
        "private-key",
        "quota",
        "referer",
        "reject",
        "save-cookies",
        "timeout",
        "tries",
        "user",
        "user-agent",
        "wait",
    }
)
SCP_SHORT_VALUES = frozenset("cDFiJloPSX")
RSYNC_SHORT_VALUES = frozenset("BefMT")
NC_SHORT_VALUES = frozenset("cegGimIOpqsTwxX")
POWERSHELL_WEB = frozenset({"invoke-webrequest", "iwr", "invoke-restmethod", "irm"})
# Switches of Invoke-WebRequest and Invoke-RestMethod; every other parameter takes a value.
POWERSHELL_SWITCHES = (
    "-allowinsecureredirect",
    "-allowunencryptedauthentication",
    "-disablekeepalive",
    "-noproxy",
    "-passthru",
    "-preserveauthorizationonredirect",
    "-preserveheaderscase",
    "-resume",
    "-skipcertificatecheck",
    "-skipheadervalidation",
    "-skiphttperrorcheck",
    "-usebasicparsing",
    "-usedefaultcredentials",
)
REMOTE_PATH = re.compile(r"^([^@/\\:]+@)?(\[[^\]/]+\]|[^@/\\:\[\]]+):(.?)")


def allowed_hosts(root: Path) -> tuple[str, ...]:
    """The hosts `[egress] allowed_hosts` names in the project's manifest; none if unreadable."""
    for name in MANIFEST_NAMES:
        path = root / name
        if not path.is_file():
            continue
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            return ()
        egress = raw.get("egress")
        hosts = egress.get("allowed_hosts") if isinstance(egress, dict) else None
        if not isinstance(hosts, list):
            return ()
        return tuple(
            host.strip().lower().rstrip(".")
            for host in hosts
            if isinstance(host, str) and host.strip()
        )
    return ()


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    for entry in allowed:
        if entry.startswith("*."):
            if host.endswith(entry[1:]) and len(host) > len(entry) - 1:
                return True
        elif host == entry:
            return True
    return False


def url_host(word: str) -> str | None:
    """The host a URL names, or None when the text does not tell it."""
    if "$" in word or "`" in word:
        return None
    try:
        host = urlsplit(word if "://" in word else f"http://{word}").hostname
    except ValueError:
        return None
    return host or None


def remote_host(word: str) -> str | None:
    """The host of a copy's destination, `""` when it is on this machine, None when unknown."""
    if word.lower().startswith(("scp://", "rsync://", "sftp://")):
        return url_host(word)
    match = REMOTE_PATH.match(word)
    if not match:
        return ""
    user, host, following = match.groups()
    host = host.strip("[]")
    if not user and len(host) == 1 and host.isalpha() and following in ("", "/", "\\"):
        return ""  # `C:/work` is a drive
    if "$" in host or "`" in host:
        return None
    return host.lower()


def _options(
    args: tuple[str, ...], short_values: frozenset[str], long_values: frozenset[str]
) -> tuple[list[tuple[str, str]], list[str]]:
    """The options a command is given, as (name, value), and its other words, in order."""
    options: list[tuple[str, str]] = []
    operands: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            operands.extend(args[index:])
            break
        if arg.startswith("--"):
            name, equals, value = arg[2:].partition("=")
            if not equals and name in long_values and index < len(args):
                value = args[index]
                index += 1
            options.append((name, value))
        elif arg.startswith("-") and len(arg) > 1:
            for position in range(1, len(arg)):
                letter = arg[position]
                if letter in short_values:  # `-d@file`, `-sT file`
                    value = arg[position + 1 :]
                    if not value and index < len(args):
                        value = args[index]
                        index += 1
                    options.append((letter, value))
                    break
                options.append((letter, ""))
        else:
            operands.append(arg)
    return options, operands


# What a command sends of this machine's, or None when it sends nothing, and the hosts it sends
# to; a host the text does not tell is None.
Outbound = tuple[str | None, list[str | None]]


def _file(name: str) -> str:
    """How a reason names what is read: `-` (and `.` for an upload) is standard input."""
    return "standard input" if name in ("-", ".", "/dev/stdin") else f"the file {name}"


def _curl(args: tuple[str, ...]) -> Outbound:
    options, operands = _options(args, CURL_SHORT_VALUES, CURL_LONG_VALUES)
    sent: list[str] = []
    for name, value in options:
        field_value = value.partition("=")[2]
        if name in ("T", "upload-file"):
            sent.append(_file(value))
        elif name in CURL_AT_FILE and value.startswith("@"):
            sent.append(_file(value[1:]))
        elif name in CURL_AT_FILE and UNKNOWN in value:
            sent.append("command output")
        elif name in CURL_AT_FILE_NAMED and "@" in value.split("=", 1)[0]:
            sent.append(_file(value.split("@", 1)[1]))
        elif name in ("F", "form") and field_value.startswith(("@", "<")):
            sent.append(_file(field_value[1:].split(";", 1)[0]))
        elif name in ("F", "form") and UNKNOWN in field_value:
            sent.append("command output")
        elif name in ("K", "config"):
            sent.append(f"what the config file {value} says")
    words = [value for name, value in options if name == "url"] + operands
    return (sent[0] if sent else None), [url_host(word) for word in words]


def _wget(args: tuple[str, ...]) -> Outbound:
    options, operands = _options(args, WGET_SHORT_VALUES, WGET_LONG_VALUES)
    sent = [_file(value) for name, value in options if name in ("post-file", "body-file")]
    return (sent[0] if sent else None), [url_host(word) for word in operands]


def _powershell_web(args: tuple[str, ...]) -> Outbound:
    sent: list[str] = []
    positional: list[str] = []
    uri: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if not arg.startswith("-") or len(arg) < 2:
            positional.append(arg)
            continue
        name, colon, value = arg.partition(":")
        name = name.lower()
        if len(name) >= 3 and any(switch.startswith(name) for switch in POWERSHELL_SWITCHES):
            continue
        if not colon and index < len(args):
            value = args[index]
            index += 1
        if len(name) >= 4 and "-infile".startswith(name):
            sent.append(_file(value))
        elif len(name) >= 3 and "-body".startswith(name) and UNKNOWN in value:
            sent.append("command output")
        elif len(name) >= 3 and "-uri".startswith(name):
            uri.append(value)
    return (sent[0] if sent else None), [url_host(word) for word in uri or positional]


def _copy(name: str, args: tuple[str, ...]) -> Outbound:
    short_values = SCP_SHORT_VALUES if name == "scp" else RSYNC_SHORT_VALUES
    _, operands = _options(args, short_values, frozenset())
    if len(operands) < 2:
        return None, []
    host = remote_host(operands[-1])
    if host == "":  # a copy to this machine
        return None, []
    return ", ".join(operands[:-1]), [host]


def _socket(args: tuple[str, ...]) -> Outbound:
    options, operands = _options(args, NC_SHORT_VALUES, frozenset())
    names = {name for name, _ in options}
    if "z" in names:  # a port check sends nothing
        return None, []
    if "l" in names or "listen" in names:
        return "its input to whoever connects", []
    hosts = [word for word in operands if not re.fullmatch(r"[\d,-]+", word)]
    if not hosts:
        return None, []
    return "its input", [None if "$" in word else word.lower() for word in hosts]


def outbound(item: SimpleCommand, powershell: bool) -> Outbound:
    """What a command sends off the machine and the hosts it sends to."""
    found: Outbound = (None, [])
    if item.name == "curl":
        found = _curl(item.args)
    elif item.name == "wget":
        found = _wget(item.args)
    elif item.name in ("scp", "rsync"):
        found = _copy(item.name, item.args)
    elif item.name in ("nc", "ncat", "netcat"):
        found = _socket(item.args)
    # In PowerShell `curl` and `wget` may be Invoke-WebRequest or the programs themselves.
    if found[0] is None and (
        item.name in POWERSHELL_WEB or (powershell and item.name in ("curl", "wget"))
    ):
        found = _powershell_web(item.args)
    if found[0] is not None and item.fed:
        return found[0], [*found[1], None]  # xargs adds words nobody can see here
    return found


def egress_reason(
    command: str, allowed: tuple[str, ...] = (), powershell: bool = False
) -> str | None:
    """Why the egress rules refuse a command line, or None when they do not."""
    try:
        commands = simple_commands(strip_heredoc_bodies(command), powershell=powershell)
    except CommandParseError as exc:
        if EGRESS_WORD.search(command):
            return f"the command line cannot be read ({exc}), so what it sends cannot be checked"
        return None
    for item in commands:
        sent, hosts = outbound(item, powershell)
        if sent is None:
            continue
        if not hosts:
            return f"{item.name} sends {sent}, and names no host it could be checked against"
        if None in hosts:
            return (
                f"{item.name} sends {sent} to a host the command line does not tell; name the "
                f"host in full so it can be checked, and {EGRESS_HINT}"
            )
        for host in hosts:
            if host is not None and not host_allowed(host, allowed):
                return f"{item.name} sends {sent} to {host}; {EGRESS_HINT}"
    return None


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
    return shell_reason(command, workspace(project, cwd), cwd, powershell) or egress_reason(
        command, allowed_hosts(Path(project)), powershell
    )


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
