"""Tests for first-class system dependency declarations and preflight."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import huge_corpus  # noqa: E402
from pipeline_fixture import Project, pipeline_available  # noqa: E402
from test_zig_toolchain import fake_zig  # noqa: E402

APP = """
app: #Module & {
	kind: "exe"
	root: "src/main.zig"
}
"""


def script(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def fake_pkg_config(directory: Path, known: tuple[str, ...]) -> Path:
    """A pkg-config that knows exactly the libraries in `known`."""
    cases = "|".join(known) if known else "__none__"
    return script(
        directory,
        "pkg-config",
        'for last; do :; done\n'
        f'case "$last" in {cases}) exit 0 ;; esac\n'
        'echo "Package \'$last\' not found" >&2\nexit 1\n',
    )


class CorpusRequirements(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.cache = self.root / "toolchains"
        self.saved_env = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("AZAZEL_ZIG_"):
                del os.environ[key]
        os.environ["PATH"] = str(self.bin)
        os.environ["HOME"] = str(self.root / "home")
        os.environ["AZAZEL_TOOLCHAIN_ROOT"] = str(self.cache)
        huge_corpus._RESOLUTIONS.clear()
        self.clones: list[str] = []
        self.saved_clone = huge_corpus.ensure_clone
        huge_corpus.ensure_clone = lambda root, repo: self.clones.append(repo.name) or (root / repo.name)
        self.river = huge_corpus.select_repos(["river"])[0]

    def tearDown(self) -> None:
        huge_corpus.ensure_clone = self.saved_clone
        os.environ.clear()
        os.environ.update(self.saved_env)
        huge_corpus._RESOLUTIONS.clear()
        self.tmp.cleanup()

    def install_wayland(self) -> None:
        script(self.bin, "wayland-scanner", "exit 0\n")
        fake_pkg_config(self.bin, self.river.pkg_config_libs)

    def test_requirements_are_typed(self) -> None:
        kinds = {(item.kind, item.name) for item in self.river.requirements}
        self.assertIn(("tool", "wayland-scanner"), kinds)
        self.assertIn(("pkg_config", "wlroots-0.20"), kinds)
        self.assertEqual(self.river.required_tools, ("pkg-config", "wayland-scanner"))
        with self.assertRaises(ValueError):
            huge_corpus.SystemRequirement("x", "daemon")

    def test_missing_tool_is_a_declared_requirement(self) -> None:
        preflight = huge_corpus.system_preflight(self.river)
        self.assertFalse(preflight["ready"])
        self.assertIn("tool:wayland-scanner", preflight["missing"])
        entry = next(
            item for item in preflight["requirements"] if item["kind"] == "tool" and item["name"] == "wayland-scanner"
        )
        self.assertEqual((entry["checked"], entry["found"]), (True, False))
        self.assertIn("missing declared system requirement: tool wayland-scanner", preflight["diagnostic"])

    def test_pkg_config_absent_is_named(self) -> None:
        preflight = huge_corpus.system_preflight(self.river)
        self.assertIn("pkg-config is not on PATH", preflight["diagnostic"])

    def test_pkg_config_probe_per_library(self) -> None:
        script(self.bin, "wayland-scanner", "exit 0\n")
        fake_pkg_config(self.bin, ("wayland-scanner", "xkbcommon"))
        preflight = huge_corpus.system_preflight(self.river)
        self.assertNotIn("pkg-config:xkbcommon", preflight["missing"])
        self.assertNotIn("tool:wayland-scanner", preflight["missing"])
        self.assertIn("pkg-config:wlroots-0.20", preflight["missing"])

    def test_satisfied_host_is_ready(self) -> None:
        self.install_wayland()
        preflight = huge_corpus.system_preflight(self.river)
        self.assertTrue(preflight["ready"], preflight["diagnostic"])
        self.assertEqual(preflight["missing"], [])

    def test_platform_filter(self) -> None:
        libxev = huge_corpus.select_repos(["libxev"])[0]
        saved = huge_corpus.host_os
        try:
            huge_corpus.host_os = lambda: "linux"
            entries = huge_corpus.system_preflight(libxev)["requirements"]
            self.assertEqual([entry["applies"] for entry in entries], [False, False])
            huge_corpus.host_os = lambda: "windows"
            entries = huge_corpus.system_preflight(libxev)["requirements"]
            self.assertEqual([entry["applies"] for entry in entries], [True, True])
            # Library probes belong to the generated build. They are recorded
            # and never reported missing here.
            self.assertEqual([entry["checked"] for entry in entries], [False, False])
            self.assertTrue(huge_corpus.system_preflight(libxev)["ready"])
        finally:
            huge_corpus.host_os = saved

    def test_tool_limited_to_another_os_is_skipped(self) -> None:
        repo = huge_corpus.Repo(
            *[getattr(self.river, name) for name in (
                "name", "upstream", "fork", "notes", "preferred_zig", "baseline_command", "build_zig",
                "build_command", "expected_build_classification", "azazel_command", "expected_classification",
                "first_targets",
            )],
            requirements=(huge_corpus.tool("no-such-tool", os=("windows",)),),
        )
        saved = huge_corpus.host_os
        try:
            huge_corpus.host_os = lambda: "linux"
            self.assertTrue(huge_corpus.system_preflight(repo)["ready"])
            huge_corpus.host_os = lambda: "windows"
            self.assertFalse(huge_corpus.system_preflight(repo)["ready"])
        finally:
            huge_corpus.host_os = saved

    def test_build_reports_the_requirement_before_cloning(self) -> None:
        fake_zig(self.cache / "zig-0.16.0", "0.16.0")
        out = self.root / "out"
        out.mkdir()
        huge_corpus.run_build(out, [self.river])
        entry = json.loads((out / "build-results.json").read_text())[0]
        self.assertEqual(entry["classification"], "system-dependency")
        self.assertTrue(entry["matches_expected"])
        self.assertIn("tool wayland-scanner", entry["output"])
        self.assertIn("tool:wayland-scanner", entry["system_requirements"]["missing"])
        self.assertIn("tool:wayland-scanner", entry["next_action"])
        self.assertEqual(self.clones, [])

    def test_build_starts_once_requirements_are_met(self) -> None:
        fake_zig(self.cache / "zig-0.16.0", "0.16.0")
        self.install_wayland()
        out = self.root / "out"
        (out / "river").mkdir(parents=True)
        huge_corpus.run_build(out, [self.river])
        entry = json.loads((out / "build-results.json").read_text())[0]
        self.assertTrue(entry["system_requirements"]["ready"])
        self.assertEqual(self.clones, ["river"])

    def test_overlay_project_declares_system_deps(self) -> None:
        huge_corpus.write_overlay(self.root, self.river)
        text = (self.root / ".azazel" / "project.cue").read_text()
        self.assertIn("system_deps: [", text)
        self.assertIn('{name: "wayland-scanner", kind: "tool", hint: "part of the wayland development package"},', text)
        self.assertIn('{name: "wlroots-0.20", kind: "pkg_config"},', text)
        parity = json.loads((self.root / ".azazel" / "parity.json").read_text())
        self.assertEqual(parity["azazel"]["requirements"][1]["name"], "wayland-scanner")
        libxev = huge_corpus.select_repos(["libxev"])[0]
        self.assertIn('os: ["windows"]', huge_corpus.system_deps_cue(libxev))
        self.assertEqual(huge_corpus.system_deps_cue(huge_corpus.select_repos(["zls"])[0]), "")


@unittest.skipUnless(pipeline_available(), "needs cue and zig on PATH")
class ProjectPreflight(unittest.TestCase):
    """`system_deps` in project.cue reaches the generated build and gates it."""

    def project(self, deps: str) -> Project:
        project = Project(f"system_deps: [\n{deps}]\n{APP}")
        self.addCleanup(project.close)
        return project

    def test_missing_requirements_stop_the_build_and_are_all_named(self) -> None:
        project = self.project(
            '\t{name: "azazel-no-such-tool", kind: "tool", hint: "install it from example.org"},\n'
            '\t{name: "azazel-no-such-lib", kind: "pkg_config", hint: "apt install libnothing-dev"},\n'
            '\t{name: "azazel_no_such_header.h", kind: "header"},\n'
            '\t{name: "azazel_no_such_library", kind: "library"},\n'
            '\t{name: "no-such-dir", kind: "include_dir"},\n'
        )
        fake_pkg_config(project.root / "fakebin", ())
        result = project.zig_build(path_prefix=project.root / "fakebin")
        self.assertNotEqual(result.returncode, 0)
        out = result.stdout
        self.assertIn(
            "missing system dependency: tool azazel-no-such-tool (install it from example.org): not found on PATH", out
        )
        self.assertIn("system dependency: pkg-config library azazel-no-such-lib (apt install libnothing-dev)", out)
        self.assertIn("system dependency: header azazel_no_such_header.h", out)
        self.assertIn("system dependency: system library azazel_no_such_library", out)
        self.assertIn("missing system dependency: include directory no-such-dir: directory does not exist", out)
        self.assertFalse((project.root / "zig-out").exists(), "an artifact was built past a failed preflight")

    def test_satisfied_requirements_build(self) -> None:
        project = self.project(
            '\t{name: "sh", kind: "tool"},\n'
            '\t{name: "azazel-fake-lib", kind: "pkg_config", min_version: "1.2"},\n'
            '\t{name: "stdio.h", kind: "header"},\n'
            '\t{name: "azazel_local.h", kind: "header"},\n'
            '\t{name: "c", kind: "library"},\n'
            '\t{name: "include", kind: "include_dir"},\n'
            '\t{name: "azazel-windows-only-tool", kind: "tool", os: ["windows"]},\n'
            '\t{name: "azazel_windows_only", kind: "library", os: ["windows"]},\n'
        )
        project.write("include/azazel_local.h", "#define AZAZEL_LOCAL 1\n")
        fakebin = project.root / "fakebin"
        script(fakebin, "pkg-config", 'echo "$@" > "$(dirname "$0")/args"\nexit 0\n')
        result = project.zig_build(path_prefix=fakebin)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(list((project.root / "zig-out" / "bin").glob("app*")))
        self.assertEqual(
            (fakebin / "args").read_text().split(),
            ["--exists", "--print-errors", "--atleast-version=1.2", "azazel-fake-lib"],
        )

    @unittest.skipUnless(sys.platform == "darwin", "frameworks are an Apple concept")
    def test_frameworks(self) -> None:
        project = self.project('\t{name: "CoreFoundation", kind: "framework", os: ["macos"]},\n')
        self.assertEqual(project.zig_build("doctor").returncode, 0)
        missing = self.project('\t{name: "AzazelNoSuchFramework", kind: "framework", os: ["macos"]},\n')
        result = missing.zig_build("doctor")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("system dependency: framework AzazelNoSuchFramework", result.stdout)

    def test_cli_doctor(self) -> None:
        ok = self.project('\t{name: "sh", kind: "tool"},\n')
        result = ok.run(sys.executable, "azazel", "doctor")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("azazel: system dependencies satisfied (1 declared)", result.stdout)
        self.assertFalse((ok.root / "zig-out").exists(), "doctor must not build artifacts")

        bad = self.project('\t{name: "azazel-no-such-tool", kind: "tool"},\n')
        result = bad.run(sys.executable, "azazel", "doctor")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("missing system dependency: tool azazel-no-such-tool", result.stdout)

    def test_schema_rejects_unknown_kind_and_os(self) -> None:
        for dep in ('{name: "x", kind: "daemon"}', '{name: "x", kind: "tool", os: ["plan9"]}', '{name: "", kind: "tool"}'):
            project = self.project(f"\t{dep},\n")
            result = project.gen()
            self.assertNotEqual(result.returncode, 0, dep)

    def test_check_requires_the_export(self) -> None:
        project = self.project('\t{name: "sh", kind: "tool"},\n')
        export = (project.root / "export.cue").read_text().replace("build: system_deps: _system_deps\n", "")
        project.write("export.cue", export)
        result = project.run(sys.executable, "azazel", "check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build.system_deps is not exported", result.stdout)


if __name__ == "__main__":
    unittest.main()
