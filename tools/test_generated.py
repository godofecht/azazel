"""End-to-end tests for generated files and run-artifact outputs."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import huge_corpus  # noqa: E402
from pipeline_fixture import Project, pipeline_available, zon_text  # noqa: E402

# A host tool that compiles on Zig 0.14, 0.15 and 0.16. It avoids std.fs and
# argument helpers, which differ between those lanes, and writes
# `pub const value: u8 = <argv[1]>;` to the path in argv[2].
TOOL = r"""
const std = @import("std");
const builtin = @import("builtin");

fn emit(value: []const u8, path: [*:0]const u8) void {
    var buf: [128]u8 = undefined;
    const text = std.fmt.bufPrint(&buf, "pub const value: u8 = {s};\n", .{value}) catch unreachable;
    if (builtin.os.tag == .linux) {
        const linux = std.os.linux;
        const fd: i32 = @intCast(linux.open(path, .{ .ACCMODE = .WRONLY, .CREAT = true, .TRUNC = true }, 0o644));
        _ = linux.write(fd, text.ptr, text.len);
        _ = linux.close(fd);
    } else {
        const fd = std.c.open(path, .{ .ACCMODE = .WRONLY, .CREAT = true, .TRUNC = true }, @as(c_uint, 0o644));
        _ = std.c.write(fd, text.ptr, text.len);
        _ = std.c.close(fd);
    }
}

fn mainInit(init: std.process.Init.Minimal) void {
    var it = init.args.iterate();
    _ = it.next();
    const value = it.next().?;
    emit(value, it.next().?.ptr);
}

fn mainLegacy() void {
    emit(std.mem.span(std.os.argv[1]), std.os.argv[2]);
}

pub const main = if (@hasDecl(std.process, "Init")) mainInit else mainLegacy;
"""

GEN_SH = """set -e
value=$(cat "$1")
printf 'int gen_value(void) { return %s; }\\n' "$value" > "$2"
printf '#define GEN_OFFSET 1\\nint gen_value(void);\\n' > "$3"
"""


@unittest.skipUnless(pipeline_available(), "needs cue and zig on PATH")
class GeneratedOutputs(unittest.TestCase):
    def project(self, cue: str, **kwargs: object) -> Project:
        project = Project(cue, **kwargs)
        self.addCleanup(project.close)
        return project

    def build_and_run(self, project: Project, *args: str) -> int:
        result = project.zig_build(*args)
        self.assertEqual(result.returncode, 0, result.stdout)
        return project.run(str(project.root / "zig-out" / "bin" / "app")).returncode

    def tool_project(self, value: str = "42") -> Project:
        project = self.project(
            f"""
generated: answer: {{
	tool: {{root: "gen/answer_gen.zig", name: "answer_gen"}}
	args: [
		{{kind: "literal", value: "{value}"}},
		{{kind: "output_file", value: "answer.zig"}},
	]
	outputs: [{{name: "answer.zig"}}]
}}

app: #Module & {{
	kind: "exe"
	root: "src/main.zig"
	generated: [{{from: "answer", output: "answer.zig", as: "import", alias: "answer"}}]
}}
"""
        )
        project.write("gen/answer_gen.zig", TOOL)
        project.write("src/main.zig", 'pub fn main() u8 {\n    return @import("answer").value;\n}\n')
        return project

    def test_host_tool_output_is_imported_by_a_module(self) -> None:
        project = self.tool_project()
        self.assertEqual(self.build_and_run(project), 42)

    def test_output_paths_are_explicit_in_the_spec(self) -> None:
        project = self.tool_project()
        self.assertEqual(project.gen().returncode, 0)
        spec = (project.root / "build_spec.zig").read_text()
        self.assertIn('.name = "answer",', spec)
        self.assertIn(".producer = .tool,", spec)
        self.assertIn('.tool_root = "gen/answer_gen.zig",', spec)
        self.assertIn('.outputs = &.{ .{ .name = "answer.zig", .install = null } },', spec)
        self.assertIn(
            '.generated = &.{ .{ .from = "answer", .output = "answer.zig", .as = .import, .alias = "answer" } },', spec
        )

    def test_generate_step_produces_without_compiling_modules(self) -> None:
        project = self.tool_project()
        result = project.zig_build("generate", "--summary", "all")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("generate answer", result.stdout)
        self.assertFalse((project.root / "zig-out").exists())

    def test_command_output_feeds_c_sources_and_include_paths(self) -> None:
        project = self.project(
            """
generated: cgen: {
	command: ["sh"]
	args: [
		{kind: "input_file", value: "gen/gen.sh"},
		{kind: "input_file", value: "gen/value.txt"},
		{kind: "output_file", value: "gen.c"},
		{kind: "output_file", value: "gen.h"},
	]
	outputs: [{name: "gen.c"}, {name: "gen.h"}]
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	native: {
		c_sources: ["src/user.c"]
		link_libc: true
	}
	generated: [
		{from: "cgen", output: "gen.c", as: "c_source"},
		{from: "cgen", output: "gen.h", as: "include"},
	]
}
"""
        )
        project.write("gen/gen.sh", GEN_SH)
        project.write("gen/value.txt", "7\n")
        project.write("src/user.c", '#include "gen.h"\nint user_value(void) { return gen_value() + GEN_OFFSET; }\n')
        project.write(
            "src/main.zig",
            "extern fn user_value() c_int;\n\npub fn main() u8 {\n    return @intCast(user_value());\n}\n",
        )
        self.assertEqual(self.build_and_run(project), 8)

        # The generator reruns when a declared input file changes.
        project.write("gen/value.txt", "20\n")
        self.assertEqual(self.build_and_run(project), 21)

    def test_stdin_stdout_capture_embed_and_install(self) -> None:
        project = self.project(
            """
generated: page: {
	command: ["tr", "a-z", "A-Z"]
	stdin: "doc/page.txt"
	stdout: "page.out"
	outputs: [{name: "page.out", install: "share/doc/page.out"}]
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	generated: [{from: "page", output: "page.out", as: "embed", alias: "page"}]
}
"""
        )
        project.write("doc/page.txt", "manual page\n")
        project.write("src/main.zig", 'pub fn main() u8 {\n    return @embedFile("page")[0];\n}\n')
        self.assertEqual(self.build_and_run(project), ord("M"))
        installed = project.root / "zig-out" / "share" / "doc" / "page.out"
        self.assertEqual(installed.read_text(), "MANUAL PAGE\n")

    def test_package_exported_path_is_tracked(self) -> None:
        project = self.project(
            """
packages: tables: path: "deps/tables"

generated: unicode: {
	package: {package: "tables", named_path: "tables.txt", pass_target: false, pass_optimize: false}
	outputs: [{name: "tables.txt", install: "share/tables.txt"}]
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	generated: [{from: "unicode", output: "tables.txt", as: "embed", alias: "tables"}]
}
"""
        )
        project.add_package(
            "tables",
            'const std = @import("std");\n\n'
            "pub fn build(b: *std.Build) void {\n"
            '    b.addNamedLazyPath("tables.txt", b.addWriteFiles().add("tables.txt", "Zed"));\n'
            "}\n",
        )
        project.write_zon({"tables": {"path": "deps/tables"}})
        project.write("src/main.zig", 'pub fn main() u8 {\n    return @embedFile("tables")[0];\n}\n')
        self.assertEqual(self.build_and_run(project), ord("Z"))
        self.assertEqual((project.root / "zig-out" / "share" / "tables.txt").read_text(), "Zed")

    def assert_gen_fails(self, cue: str, message: str) -> None:
        project = self.project(cue + '\napp: #Module & {\n\tkind: "exe"\n\troot: "src/main.zig"\n}\n')
        result = project.gen()
        self.assertNotEqual(result.returncode, 0, "generation should have failed")
        self.assertIn(message, result.stdout)

    def test_generator_rejects_inconsistent_declarations(self) -> None:
        self.assert_gen_fails(
            'generated: g: {\n\tcommand: ["sh"]\n\toutputs: [{name: "x.zig"}]\n}\n',
            "declares output x.zig but no output_file argument or stdout capture produces it",
        )
        self.assert_gen_fails(
            'generated: g: {\n\tcommand: ["sh"]\n\targs: [{kind: "output_file", value: "y.zig"}, {kind: "output_file", value: "x.zig"}]\n'
            '\toutputs: [{name: "x.zig"}]\n}\n',
            "produces y.zig but does not declare it in outputs",
        )
        self.assert_gen_fails(
            'generated: g: {\n\tcommand: ["sh"]\n\ttool: {root: "a.zig", name: "a"}\n\tstdout: "x"\n\toutputs: [{name: "x"}]\n}\n',
            "must set exactly one of tool, command, package; found tool, command",
        )
        self.assert_gen_fails(
            'generated: g: {\n\tstdout: "x"\n\toutputs: [{name: "x"}]\n}\n',
            "must set exactly one of tool, command, package; found none",
        )

    def test_generator_rejects_bad_module_uses(self) -> None:
        base = 'generated: g: {\n\tcommand: ["sh"]\n\tstdout: "x"\n\toutputs: [{name: "x"}]\n}\n'
        for use, message in (
            ('{from: "nope", output: "x", as: "embed", alias: "x"}', "consumes unknown generated step nope"),
            ('{from: "g", output: "other", as: "embed", alias: "x"}', "which generated step g does not declare"),
            ('{from: "g", output: "x", as: "import"}', "as import and needs an alias"),
        ):
            project = self.project(
                base + f'\napp: #Module & {{\n\tkind: "exe"\n\troot: "src/main.zig"\n\tgenerated: [{use}]\n}}\n'
            )
            result = project.gen()
            self.assertNotEqual(result.returncode, 0, use)
            self.assertIn(message, result.stdout)
            self.assertFalse((project.root / ".build_spec.stamp").exists())

    def test_check_reports_missing_generator_inputs(self) -> None:
        project = self.project(
            """
generated: g: {
	tool: {root: "gen/missing.zig", name: "g"}
	args: [{kind: "input_file", value: "gen/absent.txt"}, {kind: "output_file", value: "x.zig"}]
	outputs: [{name: "x.zig"}]
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	generated: [{from: "g", output: "typo.zig", as: "import", alias: "x"}]
}
"""
        )
        result = project.azazel("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated 'g' tool root does not exist: gen/missing.zig", result.stdout)
        self.assertIn("generated 'g' input file does not exist: gen/absent.txt", result.stdout)
        self.assertIn("consumes 'typo.zig', which generated step 'g' does not declare", result.stdout)


@unittest.skipUnless(shutil.which("cue"), "needs cue on PATH")
class CorpusGeneratedSlice(unittest.TestCase):
    """The corpus runner checks the generated outputs a slice declares.

    The Zig binary is a stand-in script, so these tests cover the runner's
    bookkeeping. The real libvaxis slice needs Zig 0.16.0 and network access.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = huge_corpus.select_repos(["libvaxis"])[0]
        self.clone = self.root / "libvaxis"
        self.clone.mkdir()
        # The slice reads its packages from the repo's own manifest.
        (self.clone / "build.zig.zon").write_text(
            zon_text(
                "vaxis",
                {
                    "zigimg": {"url": "git+https://example.org/zigimg#abc", "hash": "zigimg-0.1.0-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
                    "uucode": {"url": "git+https://example.org/uucode#def", "hash": "uucode-0.2.0-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "lazy": True},
                },
            ),
            encoding="utf-8",
        )
        self.saved_env = dict(os.environ)
        self.saved = (huge_corpus.materialize_executable_parity_deps, huge_corpus.ensure_clone)
        huge_corpus.materialize_executable_parity_deps = lambda path, repo: None
        huge_corpus.ensure_clone = lambda root, repo: root / repo.name
        huge_corpus._RESOLUTIONS.clear()

    def tearDown(self) -> None:
        huge_corpus.materialize_executable_parity_deps, huge_corpus.ensure_clone = self.saved
        os.environ.clear()
        os.environ.update(self.saved_env)
        huge_corpus._RESOLUTIONS.clear()
        self.tmp.cleanup()

    def stand_in_zig(self, body: str) -> None:
        binary = self.root / "zig"
        binary.write_text(
            '#!/bin/sh\nif [ "$1" = version ]; then echo 0.16.0; exit 0; fi\n' + body, encoding="utf-8"
        )
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        os.environ["AZAZEL_ZIG_0160"] = str(binary)

    def test_slice_declares_the_generated_tables(self) -> None:
        self.assertEqual(
            self.repo.executable_parity_generated_outputs, (".azazel-install/share/vaxis/unicode_tables.zig",)
        )
        self.assertIn("generated:unicode_tables:tables.zig", self.repo.executable_parity_targets)
        huge_corpus.write_executable_parity_workspace(self.clone, self.repo)
        project = (self.clone / ".azazel" / "parity-work" / "project.cue").read_text()
        self.assertIn("generated: unicode_tables: {", project)
        self.assertIn('named_path: "tables.zig"', project)
        self.assertIn('install: "share/vaxis/unicode_tables.zig"', project)

    def test_workspace_spec_carries_the_output_path(self) -> None:
        huge_corpus.write_executable_parity_workspace(self.clone, self.repo)
        workdir = self.clone / ".azazel" / "parity-work"
        result = huge_corpus.run(["./gen_build_spec.sh"], cwd=workdir, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        spec = (workdir / "build_spec.zig").read_text()
        self.assertIn(".producer = .package,", spec)
        self.assertIn('.outputs = &.{ .{ .name = "tables.zig", .install = "share/vaxis/unicode_tables.zig" } },', spec)

    def test_build_that_leaves_no_generated_output_fails_the_slice(self) -> None:
        self.stand_in_zig("exit 0\n")
        entry = huge_corpus.executable_parity_entry(self.root, self.repo, self.clone)
        self.assertEqual(entry["classification"], "missing-generated-output")
        self.assertFalse(entry["generated_outputs_validated"])
        self.assertEqual(entry["missing_generated_outputs"], [".azazel-install/share/vaxis/unicode_tables.zig"])
        self.assertFalse(entry["matches_expected"])

    def test_empty_generated_output_fails_the_slice(self) -> None:
        self.stand_in_zig("mkdir -p .azazel-install/share/vaxis\n: > .azazel-install/share/vaxis/unicode_tables.zig\n")
        entry = huge_corpus.executable_parity_entry(self.root, self.repo, self.clone)
        self.assertEqual(entry["classification"], "missing-generated-output")

    def test_stale_output_from_an_earlier_run_does_not_count(self) -> None:
        huge_corpus.write_executable_parity_workspace(self.clone, self.repo)
        stale = self.clone / ".azazel" / "parity-work" / ".azazel-install" / "share" / "vaxis" / "unicode_tables.zig"
        stale.parent.mkdir(parents=True)
        stale.write_text("old tables\n")
        self.stand_in_zig("exit 0\n")
        entry = huge_corpus.executable_parity_entry(self.root, self.repo, self.clone)
        self.assertEqual(entry["classification"], "missing-generated-output")

    def test_parity_reports_validated_generated_outputs(self) -> None:
        self.stand_in_zig(
            "mkdir -p .azazel-install/share/vaxis\necho tables > .azazel-install/share/vaxis/unicode_tables.zig\n"
        )
        os.environ["PATH"] = f"{self.root}{os.pathsep}{os.environ['PATH']}"
        huge_corpus.parity(self.root, [self.repo])
        entry = json.loads((self.root / "parity-results.json").read_text())[0]
        generated = entry["generated_outputs"]
        self.assertTrue(generated["validated"])
        self.assertEqual(generated["classification"], "ok")
        self.assertEqual(generated["declared"], [".azazel-install/share/vaxis/unicode_tables.zig"])


if __name__ == "__main__":
    unittest.main()
