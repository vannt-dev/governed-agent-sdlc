#!/usr/bin/env python
"""PreToolUse guard: agents do not send local files or command output off the machine.

The command line is read by `command_line.py`, so a rule fires on a command that runs and not on
text that names one: `git commit -m "never curl -T .env"` passes, while `bash -c "curl -T x URL"`
is refused. Heredoc bodies are data. Refused, unless every destination is an allowed host:

- `curl` with a file or standard input as the body: `-d @file`, `--data-binary @file`,
  `--json @file`, `--data-urlencode name@file`, `-F field=@file`, `-F field=<file`, `-T file`,
  `--upload-file file`, a body made of a command's output (`-d "$(cat x)"`), and `-K file`,
  whose options cannot be read;
- `wget --post-file file` and `wget --body-file file`;
- `scp` and `rsync` whose destination (the last path) is on another host: `host:path`,
  `user@host:path`, `host::module`, `scp://host/...`, `rsync://host/...`;
- PowerShell's `Invoke-WebRequest`, `Invoke-RestMethod` (and `iwr`, `irm`, `curl`, `wget`, its
  aliases) with `-InFile file` or a `-Body` made of a command's output;
- `nc`, `ncat` and `netcat`, which send whatever they are given, except a port check (`-z`); a
  listener (`-l`) is refused as well, as it hands its input to whoever connects.

Allowed: a plain GET or download, data written on the command line itself (`-d 'a=1'`,
`--data-raw`, `--form-string`, `wget --post-data`), a copy from another host to this one
(`scp host:file .`), and any upload to a host listed in the manifest:

    [egress]
    allowed_hosts = ["uploads.example.com", "*.internal.example.com"]

A name matches itself only; `*.example.com` matches every host below `example.com`. A destination
the text does not tell (a variable, a substitution, a URL without a host) is not allowed, and a
command line that cannot be read is refused when it names one of these commands.

Not attempted: other programs that send data (`ssh host < file`, `python -c ...`, `git push` to a
new remote), a script file, and aliases. This is a guard against a mistake, not a sandbox.

`src/agentkit/codex_hook.py` carries the same rules for Codex; `tests/test_guards.py` runs one
command table against both.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from command_line import UNKNOWN, CommandParseError, SimpleCommand, simple_commands
from common import deny, input_error, read_hook_input, tool_input, tool_input_error
from guard_credentials import strip_heredoc_bodies

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
    malformed = input_error(data)
    if malformed:
        return malformed
    malformed_tool = tool_input_error(data)
    if malformed_tool:
        return malformed_tool
    command = str(tool_input(data).get("command") or "")
    if not command:
        return None
    project = Path(__file__).resolve().parents[1]
    powershell = str(data.get("tool_name") or "").lower() == "powershell"
    return egress_reason(command, allowed_hosts(project), powershell)


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
