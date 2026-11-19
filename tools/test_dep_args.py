"""Tests for typed dependency options."""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dep_options  # noqa: E402
import huge_corpus  # noqa: E402
from pipeline_fixture import AZAZEL_ROOT, Project, pipeline_available  # noqa: E402

# A dependency with one option of every shape the model carries.
OPTS_BUILD = r"""
const std = @import("std");

pub const Mode = enum { fast, safe, tiny };

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const flag = b.option(bool, "flag", "a bool") orelse false;
    const count = b.option(u32, "count", "an int") orelse 0;
    const wide = b.option(i64, "wide", "a signed int") orelse 0;
    const label = b.option([]const u8, "label", "a string") orelse "none";
    const names = b.option([]const []const u8, "names", "a string list") orelse &.{};
    const mode = b.option(Mode, "mode", "an enum") orelse .fast;
    const odd = b.option(bool, "with-odd-name", "a name that is not an identifier") orelse false;

    const names_text = std.mem.join(b.allocator, ",", names) catch @panic("OOM");
    const report = b.fmt(
        "flag={}\ncount={d}\nwide={d}\nlabel={s}\nnames={s}\nmode={s}\nodd={}\narch={s}\noptimize={s}\n",
        .{ flag, count, wide, label, names_text, @tagName(mode), odd, @tagName(target.result.cpu.arch), @tagName(optimize) },
    );
    b.addNamedLazyPath("report.txt", b.addWriteFiles().add("report.txt", report));

    const options = b.addOptions();
    options.addOption(bool, "flag", flag);
    options.addOption(u32, "count", count);
    options.addOption(i64, "wide", wide);
    options.addOption([]const u8, "label", label);
    options.addOption([]const u8, "names", names_text);
    options.addOption([]const u8, "mode", @tagName(mode));
    options.addOption(bool, "odd", odd);
    const root = b.addModule("root", .{ .root_source_file = b.path("root.zig") });
    root.addOptions("config", options);
}
"""

OPTS_ROOT = "pub const config = @import(\"config\");\n"

OPTS_PROJECT = """
packages: opts: path: "deps/opts"

_opts_args: [
	{name: "flag", kind: "bool", value: true},
	{name: "count", kind: "int", value: 7},
	{name: "wide", kind: "int", value: -9000000000},
	{name: "label", kind: "string", value: "caf\\u00e9 \\"quoted\\""},
	{name: "names", kind: "string_list", value: ["alpha", "beta gamma", ""]},
	{name: "mode", kind: "enum", value: "safe"},
	{name: "with-odd-name", kind: "bool", value: true},
]

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	pkg_imports: [{alias: "opts", package: "opts", module: "root", args: _opts_args}]
}
"""

# Exit code 0 when every option arrived with the value the project gave it.
OPTS_MAIN = r"""
const std = @import("std");
const c = @import("opts").config;

pub fn main() u8 {
    if (!c.flag) return 1;
    if (c.count != 7) return 2;
    if (c.wide != -9000000000) return 3;
    if (!std.mem.eql(u8, c.label, "caf\xc3\xa9 \"quoted\"")) return 4;
    if (!std.mem.eql(u8, c.names, "alpha,beta gamma,")) return 5;
    if (!std.mem.eql(u8, c.mode, "safe")) return 6;
    if (!c.odd) return 7;
    return 0;
}
"""


def add_opts(project: Project, build: str = OPTS_BUILD) -> None:
    project.add_package("opts", build, {"root.zig": OPTS_ROOT})
    project.write_zon({"opts": {"path": "deps/opts"}})


@unittest.skipUnless(pipeline_available(), "needs cue and zig on PATH")
class DependencyOptionsBuild(unittest.TestCase):
    """The real CLI, generator and `zig build`: each option reaches the dependency."""

    def project(self, cue: str, main: str | None = None) -> Project:
        project = Project(cue)
        self.addCleanup(project.close)
        add_opts(project)
        project.write("src/main.zig", main or "pub fn main() void {}\n")
        return project

    def test_every_value_kind_reaches_the_dependency(self) -> None:
        project = self.project(OPTS_PROJECT, OPTS_MAIN)
        result = project.zig_build()
        self.assertEqual(result.returncode, 0, result.stdout)
        run = project.run(str(project.root / "zig-out" / "bin" / "app"))
        self.assertEqual(run.returncode, 0, f"option {run.returncode} did not arrive")

    def test_target_and_optimize_literals_reach_the_dependency(self) -> None:
        project = self.project(
            """
packages: opts: path: "deps/opts"

generated: report: {
	package: {
		package: "opts"
		named_path: "report.txt"
		pass_target: false
		pass_optimize: false
		args: [
			{name: "target", kind: "target", value: "aarch64-linux-gnu"},
			{name: "optimize", kind: "optimize", value: "ReleaseSmall"},
			{name: "mode", kind: "enum", value: "tiny"},
		]
	}
	outputs: [{name: "report.txt", install: "share/report.txt"}]
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
}
"""
        )
        result = project.zig_build()
        self.assertEqual(result.returncode, 0, result.stdout)
        report = (project.root / "zig-out" / "share" / "report.txt").read_text()
        self.assertIn("arch=aarch64\n", report)
        self.assertIn("optimize=ReleaseSmall\n", report)
        self.assertIn("mode=tiny\n", report)

    def test_forwarded_target_and_optimize_are_the_default(self) -> None:
        project = self.project(
            """
packages: opts: path: "deps/opts"

generated: report: {
	package: {package: "opts", named_path: "report.txt", optimize: "ReleaseFast"}
	outputs: [{name: "report.txt", install: "share/report.txt"}]
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
}
"""
        )
        result = project.zig_build("-Dtarget=x86_64-linux-gnu")
        self.assertEqual(result.returncode, 0, result.stdout)
        report = (project.root / "zig-out" / "share" / "report.txt").read_text()
        self.assertIn("arch=x86_64\n", report)
        self.assertIn("optimize=ReleaseFast\n", report)

    def test_import_and_artifact_with_the_same_options_share_one_call(self) -> None:
        project = self.project(
            OPTS_PROJECT.replace(
                "pkg_imports: [",
                'pkg_artifacts: [{package: "opts", artifact: "missing", args: _opts_args}]\n\tpkg_imports: [',
            ),
            OPTS_MAIN,
        )
        self.assertEqual(project.gen().returncode, 0)
        spec = (project.root / "build_spec.zig").read_text()
        self.assertEqual(spec.count("\nfn dep_"), 1)

    def test_the_spec_carries_the_options_as_zig_source(self) -> None:
        project = self.project(OPTS_PROJECT, OPTS_MAIN)
        self.assertEqual(project.gen().returncode, 0)
        spec = (project.root / "build_spec.zig").read_text()
        self.assertIn('.@"mode" = .@"safe"', spec)
        self.assertIn('.@"count" = 7', spec)
        self.assertIn('.@"wide" = -9000000000', spec)
        self.assertIn('.@"with-odd-name" = true', spec)
        self.assertIn('.@"names" = @as([]const []const u8, &.{ "alpha", "beta gamma", "" })', spec)
        self.assertIn('.@"label" = @as([]const u8, "caf\\xc3\\xa9 \\"quoted\\"")', spec)
        self.assertIn('.name = "mode", .kind = .@"enum", .value = "safe"', spec)

    def test_a_lazy_package_resolves_through_lazy_dependency(self) -> None:
        project = self.project(OPTS_PROJECT.replace('packages: opts: path: "deps/opts"', 'packages: opts: {path: "deps/opts", lazy: true}'), OPTS_MAIN)
        self.assertEqual(project.gen().returncode, 0)
        spec = (project.root / "build_spec.zig").read_text()
        self.assertIn('return b.lazyDependency("opts", .{', spec)


class NoHardcodedOptions(unittest.TestCase):
    """The executor carries no option names of any dependency."""

    def test_build_zig_has_no_backend_dispatch(self) -> None:
        text = (AZAZEL_ROOT / "build.zig").read_text()
        for needle in ("glfw_wgpu", "sdl3_gpu", "dependencyWithBackend", "dependencyWithFields", ".backend", ".fields"):
            self.assertNotIn(needle, text)

    def test_schema_has_no_backend_or_fields(self) -> None:
        text = (AZAZEL_ROOT / "schema.cue").read_text()
        self.assertNotIn("backend?:", text)
        self.assertNotIn("fields:", text)


@unittest.skipUnless(pipeline_available(), "needs cue and zig on PATH")
class DependencyOptionDiagnostics(unittest.TestCase):
    """A bad option fails before `std.Build` can panic, and says what to change."""

    def project(self, args: str, extra: str = "") -> Project:
        project = Project(
            f"""
packages: opts: path: "deps/opts"

app: #Module & {{
	kind: "exe"
	root: "src/main.zig"
	pkg_imports: [{{alias: "opts", package: "opts", module: "root"{extra}, args: [{args}]}}]
}}
"""
        )
        self.addCleanup(project.close)
        add_opts(project)
        return project

    def assert_check_fails(self, args: str, message: str, extra: str = "") -> Project:
        project = self.project(args, extra)
        result = project.azazel("check")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stdout)
        return project

    def test_a_value_of_the_wrong_type_is_rejected_by_the_schema(self) -> None:
        project = self.project('{name: "flag", kind: "bool", value: "yes"}')
        for result in (project.azazel("check"), project.gen()):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("conflicting values", result.stdout)
            self.assertIn("pkg_imports", result.stdout)

    def test_an_int_option_rejects_a_string(self) -> None:
        project = self.project('{name: "count", kind: "int", value: "7"}')
        self.assertNotEqual(project.gen().returncode, 0)

    def test_the_old_one_off_fields_are_gone(self) -> None:
        for field in ('backend: "glfw"', 'fields: ["x"]'):
            project = Project(
                f"""
packages: opts: path: "deps/opts"

app: #Module & {{
	kind: "exe"
	root: "src/main.zig"
	pkg_imports: [{{alias: "opts", package: "opts", module: "root", {field}}}]
}}
"""
            )
            self.addCleanup(project.close)
            result = project.gen()
            self.assertNotEqual(result.returncode, 0, field)
            self.assertIn(field.split(":")[0], result.stdout)

    def test_an_unknown_option_name_gets_a_suggestion(self) -> None:
        self.assert_check_fails(
            '{name: "flg", kind: "bool", value: true}',
            "module 'app' imports package 'opts': option 'flg' for package 'opts' is not declared by opts/build.zig",
        )
        project = self.project('{name: "flg", kind: "bool", value: true}')
        self.assertIn("did you mean 'flag'?", project.azazel("check").stdout)

    def test_the_message_lists_what_the_dependency_declares(self) -> None:
        project = self.project('{name: "nope", kind: "bool", value: true}')
        out = project.azazel("check").stdout
        self.assertIn("declared: count, flag, label, mode, names, optimize, target, wide, with-odd-name", out)

    def test_a_kind_that_does_not_match_the_declared_type(self) -> None:
        self.assert_check_fails(
            '{name: "count", kind: "bool", value: true}',
            "option 'count' for package 'opts' is passed as bool, but opts/build.zig:",
        )
        project = self.project('{name: "count", kind: "bool", value: true}')
        self.assertIn("declares it as u32 (int)", project.azazel("check").stdout)

    def test_an_enum_tag_the_dependency_does_not_define(self) -> None:
        project = self.project('{name: "mode", kind: "enum", value: "turbo"}')
        out = project.azazel("check").stdout
        self.assertIn("option 'mode' for package 'opts' is given tag 'turbo', which its enum does not define", out)
        self.assertIn("tags: fast, safe, tiny", out)

    def test_a_valid_enum_tag_passes(self) -> None:
        project = self.project('{name: "mode", kind: "enum", value: "tiny"}')
        result = project.azazel("check")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_unchecked_skips_the_comparison(self) -> None:
        project = self.project('{name: "elsewhere", kind: "bool", value: true, unchecked: true}')
        result = project.azazel("check")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_target_passed_twice(self) -> None:
        self.assert_check_fails(
            '{name: "target", kind: "target", value: "aarch64-linux-gnu"}',
            "option 'target' is passed twice; set pass_target: false to give it your own value",
        )
        project = self.project('{name: "target", kind: "target", value: "aarch64-linux-gnu"}')
        gen = project.gen()
        self.assertNotEqual(gen.returncode, 0)
        self.assertIn("option \"target\" is passed twice; set pass_target: false to give it your own value", gen.stdout)

    def test_an_option_named_twice(self) -> None:
        project = self.project('{name: "flag", kind: "bool", value: true}, {name: "flag", kind: "bool", value: false}')
        self.assertIn("option 'flag' is passed twice", project.azazel("check").stdout)
        self.assertNotEqual(project.gen().returncode, 0)

    def test_a_bad_target_triple_and_optimize_mode(self) -> None:
        project = self.project('{name: "t", kind: "target", value: "not a triple"}', ', pass_target: false')
        self.assertNotEqual(project.gen().returncode, 0)
        project = self.project('{name: "o", kind: "optimize", value: "Fastest"}')
        self.assertNotEqual(project.gen().returncode, 0)

    def test_an_unknown_kind(self) -> None:
        project = self.project('{name: "flag", kind: "float", value: 1.5}')
        self.assertNotEqual(project.gen().returncode, 0)


class ArgErrorsAndScanning(unittest.TestCase):
    def test_arg_errors_without_a_dependency(self) -> None:
        item = {
            "args": [
                {"name": "a", "kind": "bool", "value": 1},
                {"name": "b", "kind": "int", "value": True},
                {"name": "c", "kind": "string_list", "value": "x"},
                {"name": "d", "kind": "optimize", "value": "Fast"},
                {"name": "e", "kind": "enum", "value": ""},
                {"name": "f", "kind": "quaternion", "value": 1},
            ]
        }
        errors = dep_options.arg_errors("use", item)
        self.assertEqual(len(errors), 6, errors)
        self.assertIn("option 'a' is a bool and was given an integer: 1", errors[0])
        self.assertIn("option 'b' is an int and was given a bool: True", errors[1])
        self.assertIn("the supported kinds are bool, int, string, string_list, enum, target, optimize", errors[5])

    def test_scan_reads_types_and_enum_tags(self) -> None:
        text = textwrap.dedent(
            """
            const std = @import("std");
            pub const Backend = enum(u8) {
                no_backend, // the default
                glfw_wgpu = 2,
                @"sdl-3",
            };
            pub fn build(b: *std.Build) void {
                _ = b.standardOptimizeOption(.{});
                const x = b.option(Backend, "backend", "Backend to build") orelse .no_backend;
                const y = b.option(
                    []const []const u8,
                    "fields",
                    "tables, with a comma, in the text",
                ) orelse &.{};
                const z = b.option(?u32, "size", "size");
                const t = b.option(std.builtin.OptimizeMode, "mode", "mode");
                _ = .{ x, y, z, t };
            }
            """
        )
        scan = dep_options.scan_build_script(text)
        self.assertEqual(scan.options["backend"].kind, "enum")
        self.assertEqual(scan.options["backend"].tags, ("no_backend", "glfw_wgpu", "sdl-3"))
        self.assertEqual(scan.options["fields"].kind, "string_list")
        self.assertEqual(scan.options["size"].kind, "int")
        self.assertEqual(scan.options["mode"].kind, "optimize")
        self.assertEqual(scan.options["optimize"].kind, "optimize")
        self.assertNotIn("target", scan.options)

    def test_a_dependency_with_no_options_is_not_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "dep"
            package.mkdir()
            (package / "build.zig").write_text('pub fn build(b: *@import("std").Build) void { _ = b; }\n')
            item = {"args": [{"name": "anything", "kind": "bool", "value": True}]}
            errors = dep_options.package_use_errors("use", "dep", item, {"dep": {"path": "dep"}}, Path(tmp))
            self.assertEqual(errors, [])

    def test_the_real_zgui_and_zgpu_shapes(self) -> None:
        zgui = textwrap.dedent(
            """
            pub const Backend = enum { no_backend, glfw_wgpu, glfw_opengl3 };
            pub fn build(b: *std.Build) void {
                const options = .{
                    .backend = b.option(Backend, "backend", "Backend to build (default: no_backend)") orelse .no_backend,
                    .with_implot = b.option(
                        bool,
                        "with_implot",
                        "Build with bundled implot source",
                    ) orelse false,
                };
            }
            """
        )
        scan = dep_options.scan_build_script(zgui, "zgui/build.zig")
        good = {"args": [{"name": "backend", "kind": "enum", "value": "glfw_wgpu"}, {"name": "with_implot", "kind": "bool", "value": True}]}
        self.assertEqual(dep_options.check_against("use", "zgui", good, scan), [])
        bad = {"args": [{"name": "backend", "kind": "enum", "value": "glfw_wgpuu"}]}
        (error,) = dep_options.check_against("use", "zgui", bad, scan)
        self.assertIn("tags: no_backend, glfw_wgpu, glfw_opengl3", error)


class CorpusSlicesUseOptions(unittest.TestCase):
    """The corpus declarations moved onto the generic arguments."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def workspace_text(self, name: str) -> str:
        repo = next(item for item in huge_corpus.REPOS if item.name == name)
        clone = Path(self.tmp.name) / name
        clone.mkdir()
        if name == "libvaxis":
            from pipeline_fixture import zon_text

            (clone / "build.zig.zon").write_text(
                zon_text(
                    "vaxis",
                    {
                        "zigimg": {"url": "git+https://example.org/zigimg#abc", "hash": "zigimg-0.1.0-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
                        "uucode": {"url": "git+https://example.org/uucode#def", "hash": "uucode-0.2.0-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "lazy": True},
                    },
                )
            )
        huge_corpus.write_executable_parity_workspace(clone, repo)
        return (clone / ".azazel" / "parity-work" / "project.cue").read_text()

    def test_libvaxis_passes_uucode_fields_as_a_string_list(self) -> None:
        text = self.workspace_text("libvaxis")
        self.assertIn('kind: "string_list"', text)
        self.assertIn('name: "fields"', text)
        self.assertNotIn("fields: _unicode_fields", text)
        self.assertEqual(text.count("args: _uucode_args"), 2)

    def test_zig_gamedev_passes_zgui_backend_as_an_enum_and_zgpu_ints(self) -> None:
        text = self.workspace_text("zig-gamedev")
        self.assertIn('{name: "backend", kind: "enum", value: "glfw_wgpu"}', text)
        self.assertIn('{name: "with_implot", kind: "bool", value: true}', text)
        self.assertIn('{name: "buffer_pool_size", kind: "int", value: 256}', text)
        self.assertNotIn('backend: "glfw_wgpu"', text)
        self.assertEqual(text.count("args: _zgui_args"), 2)
        self.assertEqual(text.count("args: _zgpu_args"), 2)


if __name__ == "__main__":
    unittest.main()
