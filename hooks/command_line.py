"""A command line as the simple commands it runs, for the guards that judge commands.

A rule about a command has to look at the command, not at text that mentions it: in
`echo "a; rm -rf /"` nothing is deleted, in `echo a; rm -rf /` everything is. So the line is cut at
the operators that stand outside quotes (`;`, `&&`, `||`, `|`, `&`, a new line, `( )`, `{ }`), each
piece becomes shell words through `shlex`, and what is left is a list of simple commands:

- the body of `$( )`, of backquotes and of `( )` is read as commands of its own;
- the text handed to `bash -c`, `sh -c`, `eval`, `powershell -Command` and `cmd /c` is read again
  as a command line;
- `NAME=value` prefixes, redirections and the wrappers `sudo`, `command`, `exec`, `env`, `xargs`,
  `nohup`, `nice`, `time`, `timeout` are taken off, so the command behind them is the one judged.

A line that cannot be read (a quote or a bracket left open, nesting too deep) raises
`CommandParseError`; the caller decides what that means. PowerShell differs in two ways the caller
can ask for: the backquote escapes, and `@' '@` here-strings are data.

Not attempted: variables are not expanded, aliases and functions are not followed, and a script
file is not opened. `src/agentkit/codex_hook.py` carries the same text for Codex.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


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
