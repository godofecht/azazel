"""Tests for nested workspaces, subprojects and target slices."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import huge_corpus  # noqa: E402
import workspace  # noqa: E402
import zig_toolchain  # noqa: E402
from pipeline_fixture import Project, pipeline_available, zon_text  # noqa: E402

CASES = Path(__file__).resolve().parent / "glob_cases.txt"


class GlobMatching(unittest.TestCase):
    def test_every_shared_case(self) -> None:
        count = 0
        for line in CASES.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            pattern, text, verdict = line.split("\t")
            self.assertEqual(workspace.glob_match(pattern, text), verdict == "match", line)
            count += 1
        self.assertGreaterEqual(count, 20)

    def test_the_issue_examples(self) -> None:
        self.assertTrue(workspace.glob_match("samples/minimal_*", "samples/minimal_glfw_gl"))
        self.assertFalse(workspace.glob_match("samples/minimal_*", "samples/triangle_wgpu"))
        self.assertTrue(workspace.glob_match("port/*/*", "port/raspberrypi/rp2xxx"))


def export(modules: dict[str, dict], subprojects: dict[str, dict]) -> dict:
    return {"modules": modules, "subprojects": subprojects}


def module(root: str, subproject: str = "", kind: str = "exe", link: str = "abi") -> dict:
    return {"kind": kind, "root": root, "subproject": subproject, "link": link}


class CoreSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.data = export(
            {
                "app": module("src/main.zig"),
                "alpha": module("apps/alpha/main.zig", "alpha"),
                "beta": module("apps/beta/main.zig", "beta"),
                "inner": module("libs/gamma/inner/lib.zig", "inner", kind="static"),
                "glue": module("libs/gamma/glue.zig", "gamma", kind="module", link="import"),
            },
            {
                "alpha": {"path": "apps/alpha", "output_dir": "out/alpha"},
                "beta": {"path": "apps/beta"},
                "gamma": {"path": "libs/gamma"},
                "inner": {"path": "libs/gamma/inner", "output_dir": "out/inner"},
            },
        )
        self.targets = workspace.module_targets(self.data)

    def names(self, *args: tuple[str, ...]) -> list[str]:
        return [t.name for t in workspace.select(self.targets, *args)]

    def test_no_selection_selects_everything(self) -> None:
        self.assertEqual(self.names(), ["app", "alpha", "beta", "inner", "glue"])

    def test_target_paths(self) -> None:
        paths = {t.name: t.target_path for t in self.targets}
        self.assertEqual(paths["app"], "app")
        self.assertEqual(paths["alpha"], "apps/alpha/alpha")
        self.assertEqual(paths["inner"], "libs/gamma/inner/inner")

    def test_slice_matches_a_subproject_path(self) -> None:
        self.assertEqual(self.names(("apps/*",), ()), ["alpha", "beta"])
        self.assertEqual(self.names(("apps/a*",), ()), ["alpha"])

    def test_slice_matches_a_target_path(self) -> None:
        self.assertEqual(self.names(("apps/*/alpha",), ()), ["alpha"])
        self.assertEqual(self.names(("app",), ()), ["app"])

    def test_nested_workspace_is_selected_with_its_parent_by_a_deep_glob(self) -> None:
        self.assertEqual(self.names(("libs/**",), ()), ["inner", "glue"])
        self.assertEqual(self.names(("libs/gamma",), ()), ["glue"])
        # `libs/gamma/*` reaches the nested subproject and gamma's own module.
        self.assertEqual(self.names(("libs/gamma/*",), ()), ["inner", "glue"])
        self.assertEqual(self.names(("libs/gamma/inner",), ()), ["inner"])

    def test_subproject_by_name(self) -> None:
        self.assertEqual(self.names((), ("beta", "inner")), ["beta", "inner"])

    def test_slices_and_subprojects_add_up(self) -> None:
        self.assertEqual(self.names(("app",), ("alpha",)), ["app", "alpha"])

    def test_install_directories_follow_output_dir(self) -> None:
        installs = {t.name: t.install_dir for t in self.targets}
        self.assertEqual(installs["alpha"], "out/alpha/bin")
        self.assertEqual(installs["beta"], "bin")
        self.assertEqual(installs["inner"], "out/inner/lib")
        self.assertEqual(installs["glue"], "")

    def test_nesting(self) -> None:
        self.assertEqual(workspace.nesting(self.data["subprojects"]), {"inner": "gamma"})

    def test_unknown_selection_is_reported_with_what_exists(self) -> None:
        errors = workspace.selection_errors(self.data, ("nothing/*",), ("missing",))
        self.assertEqual(len(errors), 2)
        self.assertIn("subproject 'missing' is not declared", errors[0])
        self.assertIn("alpha, beta, gamma, inner", errors[0])
        self.assertIn("slice 'nothing/*' matches no module", errors[1])
        self.assertIn("apps/alpha/alpha", errors[1])
        self.assertEqual(workspace.selection_errors(self.data, ("apps/*",), ("alpha",)), [])


class SubprojectValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "apps" / "alpha").mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def errors(self, modules: dict, subprojects: dict) -> list[str]:
        return workspace.subproject_errors(export(modules, subprojects), self.root)

    def test_valid(self) -> None:
        self.assertEqual(
            self.errors({"a": module("apps/alpha/main.zig", "alpha")}, {"alpha": {"path": "apps/alpha"}}), []
        )

    def test_every_error_names_its_subproject(self) -> None:
        errors = self.errors(
            {
                "a": module("elsewhere/main.zig", "alpha"),
                "b": module("apps/alpha/b.zig", "ghost"),
            },
            {
                "alpha": {"path": "apps/alpha"},
                "dup": {"path": "apps/alpha"},
                "gone": {"path": "apps/gone"},
                "up": {"path": "../outside"},
                "abs": {"path": "/etc"},
                "out": {"path": "apps/alpha", "output_dir": "../x"},
            },
        )
        text = "\n".join(errors)
        self.assertIn("subproject 'alpha' (apps/alpha): module 'a' root elsewhere/main.zig lies outside it", text)
        self.assertIn("module 'b' belongs to subproject 'ghost', which is not declared", text)
        self.assertIn("subproject 'dup' (apps/alpha): same path as subproject 'alpha'", text)
        self.assertIn("subproject 'gone' (apps/gone): directory does not exist", text)
        self.assertIn("subproject 'up' (../outside): path must be a normalized relative path", text)
        self.assertIn("subproject 'abs' (/etc): path must be a normalized relative path", text)
        self.assertIn("output_dir must be a normalized relative path", text)


@unittest.skipUnless(pipeline_available(), "needs cue and zig on PATH")
class Pipeline(unittest.TestCase):
    """The real CLI, generator and `zig build` against a nested layout."""

    CUE = """
subprojects: {
	alpha: {path: "apps/alpha", output_dir: "out/alpha"}
	beta: {path: "apps/beta"}
	gamma: {path: "libs/gamma"}
	inner: {path: "libs/gamma/inner", output_dir: "out/inner"}
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
}

alpha: #Module & {
	kind: "exe"
	subproject: "alpha"
	root: "apps/alpha/main.zig"
}

// beta does not compile. Building any other slice must not touch it.
beta: #Module & {
	kind: "exe"
	subproject: "beta"
	root: "apps/beta/main.zig"
}

inner: #Module & {
	kind: "static"
	subproject: "inner"
	root: "libs/gamma/inner/lib.zig"
}
"""

    def project(self, cue: str | None = None) -> Project:
        project = Project(cue or self.CUE, modules=("app", "alpha", "beta", "inner"))
        self.addCleanup(project.close)
        project.write("apps/alpha/main.zig", "pub fn main() void {}\n")
        project.write("apps/beta/main.zig", "pub fn main() void { this_does_not_compile(); }\n")
        project.write("libs/gamma/inner/lib.zig", "pub export fn inner_value() u32 {\n    return 7;\n}\n")
        return project

    def installed(self, project: Project) -> list[str]:
        out = project.root / "zig-out"
        if not out.exists():
            return []
        return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())

    def test_slice_builds_only_the_selected_subproject(self) -> None:
        project = self.project()
        result = project.azazel("build", "--slice", "apps/alpha")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("building 1 of 4 modules: apps/alpha/alpha", result.stdout)
        self.assertEqual(self.installed(project), ["out/alpha/bin/alpha"])

    def test_a_glob_slice_reaches_every_match_and_nothing_else(self) -> None:
        project = self.project()
        result = project.azazel("build", "--slice", "libs/**")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.installed(project), ["out/inner/lib/libinner.a"])

    def test_without_a_selection_the_broken_subproject_fails_the_build(self) -> None:
        project = self.project()
        result = project.azazel("build")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("this_does_not_compile", result.stdout)

    def test_the_failure_is_scoped_to_the_selected_subproject(self) -> None:
        project = self.project()
        result = project.azazel("build", "--subproject", "beta")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("apps/beta/main.zig", result.stdout)
        self.assertIn("the build failed for the selected targets under: apps/beta", result.stdout)
        self.assertNotIn("apps/alpha", result.stdout.split("building 1 of 4 modules")[-1])

    def test_subproject_step_builds_just_its_modules(self) -> None:
        project = self.project()
        result = project.zig_build("subproject-alpha")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.installed(project), ["out/alpha/bin/alpha"])

    def test_unknown_selection_fails_before_zig_runs(self) -> None:
        project = self.project()
        result = project.azazel("build", "--slice", "nothing/*")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("slice 'nothing/*' matches no module or subproject path", result.stdout)
        self.assertFalse((project.root / "zig-out").exists())

    def test_zig_rejects_an_unknown_slice_too(self) -> None:
        project = self.project()
        result = project.zig_build("-Dslice=nothing/*")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("-Dslice=nothing/* matches no module or subproject path", result.stdout)
        self.assertIn("apps/alpha/alpha", result.stdout)

    def test_targets_lists_selection_and_install_dirs(self) -> None:
        project = self.project()
        result = project.azazel("targets", "--json", "--slice", "apps/*")
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual([t["target_path"] for t in data["selected"]], ["apps/alpha/alpha", "apps/beta/beta"])
        self.assertEqual(data["selected"][0]["install_dir"], "out/alpha/bin")
        self.assertEqual(data["nesting"], {"inner": "gamma"})

    def test_check_scopes_errors_to_the_subproject(self) -> None:
        project = self.project(self.CUE.replace('root: "apps/alpha/main.zig"', 'root: "src/main.zig"'))
        result = project.azazel("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("subproject 'alpha' (apps/alpha): module 'alpha' root src/main.zig lies outside it", result.stdout)

    def test_the_generator_rejects_a_module_outside_its_subproject(self) -> None:
        project = self.project(self.CUE.replace('root: "apps/alpha/main.zig"', 'root: "src/main.zig"'))
        result = project.gen()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("module alpha root src/main.zig is outside subproject alpha (apps/alpha)", result.stdout)

    def test_the_generator_rejects_an_unknown_subproject(self) -> None:
        project = self.project(self.CUE.replace('subproject: "beta"', 'subproject: "ghost"'))
        result = project.gen()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("module beta belongs to unknown subproject ghost", result.stdout)

    def test_check_requires_the_export(self) -> None:
        project = self.project()
        export_cue = (project.root / "export.cue").read_text().replace("build: subprojects: _subprojects\n", "")
        project.write("export.cue", export_cue)
        result = project.azazel("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build.subprojects is not exported", result.stdout)


def step_build_zig(broken: tuple[str, ...] = ()) -> str:
    """A root build script with one step per sample, like zig-gamedev's.

    Each step installs the sample's payload as `bin/<name>`. A broken sample
    fails with a message of its own.
    """
    lines = ['const std = @import("std");', "pub fn build(b: *std.Build) void {"]
    for name in ("alpha", "beta", "delta"):
        if name in broken:
            lines.append(
                f'    const {name} = b.addSystemCommand(&.{{ "sh", "-c", "echo {name} failed: missing wayland-scanner >&2; exit 1" }});'
            )
            lines.append(f'    b.step("{name}", "sample {name}").dependOn(&{name}.step);')
            lines.append(f"    b.getInstallStep().dependOn(&{name}.step);")
        else:
            lines.append(f"    const {name} = b.addInstallFile(b.path(\"samples/{name}/payload.txt\"), \"bin/{name}\");")
            lines.append(f'    b.step("{name}", "sample {name}").dependOn(&{name}.step);')
            lines.append(f"    b.getInstallStep().dependOn(&{name}.step);")
    lines.append("}")
    return "\n".join(lines) + "\n"


def package_build_zig(message: str = "") -> str:
    if message:
        return (
            'const std = @import("std");\npub fn build(b: *std.Build) void {\n'
            f'    b.getInstallStep().dependOn(&b.addSystemCommand(&.{{ "sh", "-c", "echo {message} >&2; exit 1" }}).step);\n'
            "}\n"
        )
    return (
        'const std = @import("std");\npub fn build(b: *std.Build) void {\n'
        '    const f = b.addInstallFile(b.path("payload.txt"), "bin/out");\n'
        "    b.getInstallStep().dependOn(&f.step);\n}\n"
    )


@unittest.skipUnless(shutil.which("zig"), "needs zig on PATH")
class CorpusSlices(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        version = zig_toolchain.zig_version_of(shutil.which("zig"))
        self.version = version
        self.saved_env = dict(os.environ)
        for key in ("ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR"):
            os.environ.pop(key, None)
        self.saved = (
            huge_corpus.ensure_clone,
            huge_corpus.PACKAGE_CACHE,
            huge_corpus.REQUESTED_SLICES,
            huge_corpus.NARROW_PATHS,
            huge_corpus.WHOLE_REPO,
        )
        huge_corpus.ensure_clone = lambda root, repo: root / repo.name
        huge_corpus._RESOLUTIONS.clear()
        self.addCleanup(self.restore)

    def restore(self) -> None:
        (
            huge_corpus.ensure_clone,
            huge_corpus.PACKAGE_CACHE,
            huge_corpus.REQUESTED_SLICES,
            huge_corpus.NARROW_PATHS,
            huge_corpus.WHOLE_REPO,
        ) = self.saved
        os.environ.clear()
        os.environ.update(self.saved_env)
        huge_corpus._RESOLUTIONS.clear()

    def repo(self, slices: tuple[workspace.TargetSlice, ...]) -> huge_corpus.Repo:
        repo = huge_corpus.Repo(
            "fixture", "example/fixture", "example/fixture", "test fixture", self.version[:4],
            ("zig", "build", "--help"), self.version, ("zig", "build", "--summary", "all"), "unknown",
            ("azazel", "parity"), "ok", ("exe:fixture",),
            target_slices=slices,
        )
        os.environ[repo.required_toolchain().env_key] = shutil.which("zig")
        return repo

    def samples_clone(self, root_name: str, broken: tuple[str, ...] = ()) -> Path:
        root = self.base / root_name
        clone = root / "fixture"
        for name in ("alpha", "beta", "delta", "gamma"):
            (clone / "samples" / name).mkdir(parents=True)
            (clone / "samples" / name / "payload.txt").write_text(name)
            (clone / "samples" / name / "build.zig").write_text("// sample\n")
        (clone / "build.zig").write_text(step_build_zig(broken))
        (clone / "build.zig.zon").write_text(zon_text("fixture", paths=("build.zig", "build.zig.zon", "samples")))
        return root

    def ports_clone(self, root_name: str, broken: str = "") -> Path:
        root = self.base / root_name
        clone = root / "fixture"
        for vendor, chip in (("acme", "one"), ("acme", "two"), ("zeta", "three")):
            package = clone / "port" / vendor / chip
            package.mkdir(parents=True)
            (package / "payload.txt").write_text(chip)
            message = "chip two cannot find wayland-scanner" if chip == "two" else ""
            if broken and chip == broken:
                message = "chip failed in an unusual way"
            (package / "build.zig").write_text(package_build_zig(message))
            (package / "build.zig.zon").write_text(zon_text(f"chip_{chip}", paths=("build.zig", "build.zig.zon", "payload.txt")))
        (clone / "build.zig").write_text('pub fn build(b: *@import("std").Build) void { _ = b; }\n')
        return root

    def run_build(self, root: Path, repo: huge_corpus.Repo) -> dict[str, object]:
        huge_corpus.run_build(root, [repo])
        return json.loads((root / "build-results.json").read_text())[0]

    def test_discovery_finds_nested_packages_and_their_parents(self) -> None:
        root = self.ports_clone("discover")
        found = {p.path: p for p in workspace.discover_packages(root / "fixture")}
        self.assertEqual(sorted(found), ["port/acme/one", "port/acme/two", "port/zeta/three"])
        self.assertEqual(found["port/acme/one"].name, "chip_one")
        self.assertTrue(found["port/acme/one"].has_manifest)

    def test_resolution_applies_patterns_narrowing_and_known_steps(self) -> None:
        root = self.samples_clone("resolve")
        slice_ = workspace.TargetSlice("s", ("samples/*",), mode="steps")
        selection = workspace.resolve_slice(root / "fixture", slice_)
        self.assertEqual([t.path for t in selection.selected], ["samples/alpha", "samples/beta", "samples/delta", "samples/gamma"])
        narrowed = workspace.resolve_slice(root / "fixture", slice_, narrow=("samples/a*",))
        self.assertEqual([t.path for t in narrowed.selected], ["samples/alpha"])
        stepped = workspace.resolve_slice(root / "fixture", slice_, known_steps={"alpha", "beta"})
        self.assertEqual([t.path for t in stepped.selected], ["samples/alpha", "samples/beta"])
        self.assertEqual(
            [(s.path, s.skipped) for s in stepped.skipped],
            [
                ("samples/delta", "build step 'delta' is not defined for this target"),
                ("samples/gamma", "build step 'gamma' is not defined for this target"),
            ],
        )

    def test_a_steps_slice_builds_only_its_directories(self) -> None:
        # delta is broken, and the slice does not name it.
        root = self.samples_clone("steps", broken=("delta",))
        slice_ = workspace.TargetSlice("pair", ("samples/*",), mode="steps", outputs=("bin/{name}",))
        huge_corpus.NARROW_PATHS = ("samples/alpha", "samples/beta")
        entry = self.run_build(root, self.repo((slice_,)))
        self.assertEqual(entry["classification"], "ok", entry["output"])
        self.assertEqual(entry["selected_target_paths"], ["samples/alpha", "samples/beta"])
        installed = sorted(p.name for p in (root / "fixture" / "zig-out" / "bin").iterdir())
        self.assertEqual(installed, ["alpha", "beta"])
        (summary,) = entry["target_slice"]
        self.assertEqual(summary["built_paths"], ["samples/alpha", "samples/beta"])
        self.assertEqual(summary["results"][0]["outputs"]["found"], ["bin/alpha"])
        self.assertEqual(summary["results"][0]["command"][1:], ["build", "alpha", "--summary", "all"])

    def test_the_whole_repo_still_runs_the_full_build(self) -> None:
        root = self.samples_clone("whole", broken=("delta",))
        slice_ = workspace.TargetSlice("pair", ("samples/*",), mode="steps", outputs=("bin/{name}",))
        huge_corpus.WHOLE_REPO = True
        entry = self.run_build(root, self.repo((slice_,)))
        self.assertEqual(entry["target_slice"], [])
        self.assertEqual(entry["selected_target_paths"], [])
        self.assertNotEqual(entry["returncode"], 0)

    def test_a_failure_is_scoped_to_the_directory_that_failed(self) -> None:
        root = self.samples_clone("scoped", broken=("beta",))
        slice_ = workspace.TargetSlice("trio", ("samples/*",), mode="steps", outputs=("bin/{name}",))
        entry = self.run_build(root, self.repo((slice_,)))
        (summary,) = entry["target_slice"]
        self.assertEqual(summary["failed_paths"], ["samples/beta"])
        self.assertIn("samples/alpha", summary["built_paths"])
        self.assertIn("samples/delta", summary["built_paths"])
        by_path = {r["path"]: r for r in summary["results"]}
        self.assertEqual(by_path["samples/alpha"]["classification"], "ok")
        self.assertEqual(by_path["samples/beta"]["classification"], "system-dependency")
        self.assertIn("beta failed", by_path["samples/beta"]["output"])
        self.assertNotIn("alpha failed", by_path["samples/beta"]["output"])
        self.assertEqual(entry["classification"], "system-dependency")
        self.assertIn("## samples/beta (system-dependency)", entry["output"])

    def test_a_package_slice_runs_in_each_package_root(self) -> None:
        root = self.ports_clone("ports")
        slice_ = workspace.TargetSlice("ports", ("port/*/*",), mode="package", outputs=("bin/out",))
        huge_corpus.NARROW_PATHS = ("port/acme/*",)
        entry = self.run_build(root, self.repo((slice_,)))
        (summary,) = entry["target_slice"]
        self.assertEqual(entry["selected_target_paths"], ["port/acme/one", "port/acme/two"])
        by_path = {r["path"]: r for r in summary["results"]}
        self.assertEqual(by_path["port/acme/one"]["cwd"], "port/acme/one")
        self.assertEqual(by_path["port/acme/one"]["classification"], "ok")
        self.assertEqual(by_path["port/acme/one"]["output_prefix"], "port/acme/one/zig-out")
        self.assertEqual(by_path["port/acme/one"]["outputs"]["found"], ["bin/out"])
        self.assertEqual(by_path["port/acme/two"]["classification"], "system-dependency")
        self.assertTrue((root / "fixture" / "port/acme/one/zig-out/bin/out").is_file())
        self.assertFalse((root / "fixture" / "port/zeta/three/zig-out").exists())

    def test_a_missing_output_is_reported_for_that_directory(self) -> None:
        root = self.ports_clone("missing")
        slice_ = workspace.TargetSlice("ports", ("port/zeta/*",), mode="package", outputs=("bin/never",))
        entry = self.run_build(root, self.repo((slice_,)))
        self.assertEqual(entry["classification"], "missing-slice-output")
        (summary,) = entry["target_slice"]
        self.assertEqual(summary["results"][0]["outputs"]["missing"], ["bin/never"])

    def test_an_empty_slice_is_a_failure(self) -> None:
        root = self.ports_clone("empty")
        slice_ = workspace.TargetSlice("none", ("tools/*",), mode="package")
        entry = self.run_build(root, self.repo((slice_,)))
        self.assertEqual(entry["classification"], "empty-slice")
        self.assertNotEqual(entry["returncode"], 0)

    def test_parity_reports_the_selected_target_paths(self) -> None:
        root = self.ports_clone("parity")
        slice_ = workspace.TargetSlice("ports", ("port/*/*",), mode="package")
        repo = self.repo((slice_,))
        huge_corpus.NARROW_PATHS = ("port/zeta/*",)
        huge_corpus.parity(root, [repo])
        (entry,) = json.loads((root / "parity-results.json").read_text())
        self.assertEqual(entry["selected_target_paths"], ["port/zeta/three"])
        self.assertEqual(entry["target_slices"][0]["targets"][0]["root"], "port/zeta/three")
        self.assertEqual(entry["target_slices"][0]["narrowed_by"], ["port/zeta/*"])

    def test_narrowing_leaves_out_a_slice_it_empties(self) -> None:
        root = self.ports_clone("narrow")
        (root / "fixture" / "tools" / "gen").mkdir(parents=True)
        (root / "fixture" / "tools" / "gen" / "build.zig").write_text("// tool\n")
        (root / "fixture" / "tools" / "gen" / "payload.txt").write_text("x")
        ports = workspace.TargetSlice("ports", ("port/*/*",), mode="package")
        tools = workspace.TargetSlice("tools", ("tools/*",), mode="package")
        repo = self.repo((ports, tools))
        huge_corpus.NARROW_PATHS = ("tools/*",)
        self.assertEqual([s.slice.name for s in huge_corpus.slice_selections(repo, root / "fixture")], ["tools"])
        huge_corpus.NARROW_PATHS = ("nowhere/*",)
        self.assertEqual(len(huge_corpus.slice_selections(repo, root / "fixture")), 2)

    def test_dependency_unpack_directories_are_not_packages(self) -> None:
        root = self.ports_clone("unpacked")
        hidden = root / "fixture" / "port" / "acme" / "one" / "zig-pkg" / "dep-0.0.0-abc"
        hidden.mkdir(parents=True)
        (hidden / "build.zig.zon").write_text(".{}")
        found = [p.path for p in workspace.discover_packages(root / "fixture")]
        self.assertEqual(found, ["port/acme/one", "port/acme/two", "port/zeta/three"])

    def test_the_manifest_declares_slices(self) -> None:
        slice_ = workspace.TargetSlice("ports", ("port/*/*",), mode="package", outputs=("bin/out",))
        manifest = self.repo((slice_,)).manifest()
        self.assertEqual(manifest["target_slices"][0]["patterns"], ["port/*/*"])
        self.assertEqual(manifest["target_slices"][0]["outputs"], ["bin/out"])


class RealCorpusDeclarations(unittest.TestCase):
    def test_microzig_and_zig_gamedev_declare_the_issue_slices(self) -> None:
        repos = {repo.name: repo for repo in huge_corpus.REPOS}
        gamedev = {item.name: item for item in repos["zig-gamedev"].target_slices}
        self.assertEqual(gamedev["minimal-samples"].patterns, ("samples/minimal_*",))
        self.assertEqual(gamedev["minimal-samples"].mode, "steps")
        microzig = {item.name: item for item in repos["microzig"].target_slices}
        self.assertEqual(microzig["ports"].patterns, ("port/*/*",))
        self.assertEqual(microzig["ports"].mode, "package")

    def test_slice_patterns_reject_escapes(self) -> None:
        for bad in ("../x", "/abs", "a/../b"):
            with self.assertRaises(ValueError):
                workspace.TargetSlice("bad", (bad,))
        with self.assertRaises(ValueError):
            workspace.TargetSlice("bad", ("a",), mode="weird")


if __name__ == "__main__":
    unittest.main()
