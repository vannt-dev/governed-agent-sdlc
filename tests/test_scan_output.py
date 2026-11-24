from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

from agentkit import review

ROOT = Path(__file__).resolve().parents[1]


def load_hook(name: str):
    hooks = ROOT / "hooks"
    sys.path.insert(0, str(hooks))
    spec = importlib.util.spec_from_file_location(name, hooks / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = load_hook("scan_tool_output")

# Built from parts, so no file in the repository holds a whole key-shaped string.
GITHUB_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
OPENAI_KEY = "sk" + "-" + "abcdefghijklmnopqrstuvwxyz012345"
AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
PRIVATE_KEY = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEA\n"

SECRET_OUTPUTS = (
    (f"GITHUB_TOKEN={GITHUB_TOKEN}\n", "a GitHub token"),
    (f"key: {OPENAI_KEY}", "an API key (sk-...)"),
    (f"aws_access_key_id = {AWS_KEY}", "an AWS access key ID"),
    ("Authorization: Bearer " + "abcdefghijklmnop1234", "a bearer token"),
    ("DB_PASSWORD=" + "hunter2hunter2x9", "a key, secret, token or password value"),
    ('"api_key": "' + "s3cr3t-value" + '"', "a key, secret, token or password value"),
    (PRIVATE_KEY, "a private key"),
)

# Ordinary source and command output: nothing here is a secret.
PLAIN_OUTPUTS = (
    "token: string;",
    "const token = tokens[i];",
    "secret: reported",
    "password = get_password()",
    "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
    "api_key=$value",
    "On branch main\nnothing to commit, working tree clean\n",
    "Authorization: Bearer $TOKEN",
    "password = hashlib.sha256(raw).hexdigest()",
    "token = base64.b64encode(data)",
    "secret = secrets_by_name2[key]",
)


class SecretScanTests(unittest.TestCase):
    def test_secret_looking_output_is_named_by_kind(self) -> None:
        for text, kind in SECRET_OUTPUTS:
            with self.subTest(kind=kind):
                self.assertIn(kind, scan.secret_kinds({"stdout": text, "stderr": ""}))

    def test_ordinary_output_is_not_reported(self) -> None:
        for text in PLAIN_OUTPUTS:
            with self.subTest(text=text):
                self.assertEqual([], scan.secret_kinds({"stdout": text}))

    def test_every_shape_of_response_is_read(self) -> None:
        shapes = (
            GITHUB_TOKEN,  # a failed call gives the error text
            {"stdout": "", "stderr": GITHUB_TOKEN, "interrupted": False, "isImage": False},
            {"type": "text", "file": {"filePath": "a.txt", "content": f"x\n{GITHUB_TOKEN}\n"}},
            [{"type": "text", "text": GITHUB_TOKEN}],
        )
        for response in shapes:
            with self.subTest(response=type(response).__name__):
                self.assertEqual(["a GitHub token"], scan.secret_kinds(response))

    def test_the_warning_names_the_kind_and_never_the_secret(self) -> None:
        data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "cat config.txt"},
            "tool_response": {"stdout": f"{GITHUB_TOKEN}\n{AWS_KEY}\n", "stderr": ""},
        }
        result = scan.answer(data)
        assert result is not None
        output = result["hookSpecificOutput"]
        self.assertEqual("PostToolUse", output["hookEventName"])
        context = output["additionalContext"]
        self.assertIn("a GitHub token and an AWS access key ID", context)
        self.assertIn("Bash", context)
        self.assertNotIn(GITHUB_TOKEN, json.dumps(result))
        self.assertNotIn(AWS_KEY, json.dumps(result))
        self.assertNotIn("decision", result)

    def test_nothing_is_said_about_clean_or_unreadable_input(self) -> None:
        self.assertIsNone(scan.answer({"tool_name": "Bash", "tool_response": {"stdout": "ok"}}))
        self.assertIsNone(scan.answer({"tool_name": "Bash"}))
        self.assertIsNone(scan.answer(["not", "an", "object"]))

    def test_the_shared_patterns_are_the_ones_review_redacts(self) -> None:
        # the hook runs on its own, so it carries a copy; the copy must not drift
        redacted = [pattern.pattern for pattern, _ in review._SECRET_PATTERNS]
        carried = [pattern.pattern for pattern, _ in scan.SHARED_PATTERNS]
        self.assertEqual(redacted[: len(carried)], carried)
        self.assertEqual(
            [pattern.flags for pattern, _ in review._SECRET_PATTERNS][: len(carried)],
            [pattern.flags for pattern, _ in scan.SHARED_PATTERNS],
        )


class SecretScanHookTests(unittest.TestCase):
    """The hook as Claude Code runs it: JSON on standard input, an answer on standard output."""

    def run_hook(self, payload: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "scan_tool_output.py")],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_a_secret_in_the_output_is_answered_with_context(self) -> None:
        result = self.run_hook(
            {"tool_name": "Read", "tool_response": {"file": {"content": OPENAI_KEY}}}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        answer = json.loads(result.stdout)
        self.assertIn("API key", answer["hookSpecificOutput"]["additionalContext"])

    def test_clean_or_broken_input_is_answered_with_nothing(self) -> None:
        for payload in ({"tool_name": "Bash", "tool_response": {"stdout": "ok"}}, "not-json"):
            with self.subTest(payload=payload):
                result = self.run_hook(payload)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
