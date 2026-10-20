from __future__ import annotations

import contextlib
import io
import tempfile
import tomllib
import unittest
from pathlib import Path

from agentkit.cli import main

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
COMMAND_NAMES = {"format", "lint", "typecheck", "test", "build"}


def _profile(name: str) -> dict:
    return tomllib.loads((PROFILES / name / "profile.toml").read_text(encoding="utf-8"))


def _quiet(arguments: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(arguments)


class ShippedProfileTests(unittest.TestCase):
    def test_every_shipped_profile_is_well_formed(self) -> None:
        folders = sorted(path for path in PROFILES.iterdir() if path.is_dir())
        self.assertTrue(folders)
        for folder in folders:
            with self.subTest(profile=folder.name):
                data = _profile(folder.name)
                self.assertEqual(
                    {"id", "description", "source_globs", "generated_globs", "commands"}, set(data)
                )
                # the folder is what a manifest names; an id that differs could never be selected
                self.assertEqual(folder.name, data["id"])
                self.assertTrue(data["description"].strip().endswith("."))
                for key in ("source_globs", "generated_globs"):
                    self.assertIsInstance(data[key], list)
                    self.assertTrue(data[key], key)
                    self.assertTrue(all(isinstance(glob, str) and glob for glob in data[key]), key)
                self.assertLessEqual(set(data["commands"]), COMMAND_NAMES)
                self.assertTrue(all(isinstance(value, str) for value in data["commands"].values()))

    def test_the_stacks_people_work_in_have_a_profile(self) -> None:
        shipped = {path.parent.name for path in PROFILES.glob("*/profile.toml")}
        self.assertLessEqual(
            {
                "generic",
                "python",
                "dotnet",
                "nuxt",
                "node",
                "java",
                "flutter",
                "go",
                "rust",
                "kotlin",
                "php",
            },
            shipped,
        )

    def test_a_profile_names_the_commands_of_its_stack(self) -> None:
        node = _profile("node")
        self.assertEqual("npm test", node["commands"]["test"])
        self.assertIn("**/node_modules/**", node["generated_globs"])
        self.assertIn("**/*.ts", node["source_globs"])

        java = _profile("java")
        self.assertIn("mvn", java["commands"]["test"])
        self.assertIn("**/target/**", java["generated_globs"])
        self.assertIn("**/*.java", java["source_globs"])
        # a Gradle project is a Java project too: its build files are source, its output generated
        self.assertIn("**/*.gradle.kts", java["source_globs"])
        self.assertIn("**/build/**", java["generated_globs"])

        flutter = _profile("flutter")
        self.assertEqual("flutter test", flutter["commands"]["test"])
        self.assertEqual("flutter analyze", flutter["commands"]["lint"])
        self.assertIn("**/*.dart", flutter["source_globs"])
        self.assertIn("**/.dart_tool/**", flutter["generated_globs"])
        # which artefact a Flutter project builds (apk, ipa, web) is the project's to say
        self.assertNotIn("build", flutter["commands"])

    def test_go_rust_kotlin_and_php_use_the_commands_their_tools_document(self) -> None:
        # the same checks repokeeper's stack templates run in CI for these stacks
        go = _profile("go")
        self.assertIn("gofmt -l .", go["commands"]["format"])
        self.assertTrue(go["commands"]["format"].endswith("exit 1; }"))  # gofmt -l never fails
        self.assertEqual("go vet ./...", go["commands"]["lint"])
        self.assertEqual("go test ./...", go["commands"]["test"])
        self.assertIn("**/*.go", go["source_globs"])
        self.assertIn("**/go.mod", go["source_globs"])

        rust = _profile("rust")
        self.assertEqual("cargo fmt --all --check", rust["commands"]["format"])
        self.assertEqual(
            "cargo clippy --workspace --all-targets -- -D warnings", rust["commands"]["lint"]
        )
        # plain `cargo test` also runs doctests, which --all-targets would leave out
        self.assertEqual("cargo test --workspace", rust["commands"]["test"])
        self.assertIn("**/target/**", rust["generated_globs"])

        kotlin = _profile("kotlin")
        # ktlint and detekt are Gradle plugins a build applies or not; `check` runs them when
        # applied, and the tests either way, so the profile names no linter of its own
        self.assertEqual("./gradlew check", kotlin["commands"]["test"])
        self.assertNotIn("lint", kotlin["commands"])
        self.assertIn("**/*.kt", kotlin["source_globs"])
        self.assertIn("**/build/**", kotlin["generated_globs"])

        php = _profile("php")
        self.assertEqual("composer validate --no-check-publish", php["commands"]["lint"])
        self.assertEqual("vendor/bin/phpunit", php["commands"]["test"])
        # PHPStan and PHP CS Fixer need a config file the project chooses to have
        self.assertNotIn("phpstan", " ".join(php["commands"].values()))
        self.assertIn("**/vendor/**", php["generated_globs"])


class InitProfileTests(unittest.TestCase):
    def _manifest(self, project: Path) -> dict:
        return tomllib.loads((project / ".agent" / "project.toml").read_text(encoding="utf-8"))

    def test_init_with_a_profile_names_it_and_takes_its_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "shop"
            self.assertEqual(
                0, _quiet(["init", str(project), "--adapter", "none", "--profile", "node"])
            )
            manifest = self._manifest(project)
            self.assertEqual(["node"], manifest["repositories"][0]["profiles"])
            self.assertEqual(_profile("node")["commands"], manifest["commands"])
            self.assertEqual(0, _quiet(["validate", str(project)]))

    def test_init_without_a_profile_is_what_it_was(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "plain"
            self.assertEqual(0, _quiet(["init", str(project), "--adapter", "none"]))
            manifest = self._manifest(project)
            self.assertEqual(["generic"], manifest["repositories"][0]["profiles"])
            # the generic profile names no command, so the manifest gets no empty table
            self.assertNotIn("commands", manifest)

    def test_init_takes_several_profiles_and_the_first_command_of_each_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "app"
            self.assertEqual(
                0,
                _quiet(
                    [
                        "init",
                        str(project),
                        "--adapter",
                        "none",
                        "--profile",
                        "flutter",
                        "--profile",
                        "node",
                    ]
                ),
            )
            manifest = self._manifest(project)
            self.assertEqual(["flutter", "node"], manifest["repositories"][0]["profiles"])
            # flutter comes first, so its test and lint win; node adds what flutter does not name
            self.assertEqual("flutter test", manifest["commands"]["test"])
            self.assertEqual("flutter analyze", manifest["commands"]["lint"])
            self.assertEqual("npm run build", manifest["commands"]["build"])
            self.assertEqual(0, _quiet(["validate", str(project)]))

    def test_init_refuses_a_profile_that_is_not_shipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "nope"
            with self.assertRaises(SystemExit) as raised:
                _quiet(["init", str(project), "--adapter", "none", "--profile", "cobol"])
            self.assertEqual(2, raised.exception.code)
            self.assertFalse((project / ".agent").exists())

    def test_every_shipped_profile_initialises_a_project_that_validates(self) -> None:
        for name in sorted(path.parent.name for path in PROFILES.glob("*/profile.toml")):
            with self.subTest(profile=name), tempfile.TemporaryDirectory() as temp:
                project = Path(temp) / name
                self.assertEqual(
                    0, _quiet(["init", str(project), "--adapter", "none", "--profile", name])
                )
                self.assertEqual(0, _quiet(["validate", str(project)]))


if __name__ == "__main__":
    unittest.main()
