"""Tests for the declared-input closure behind the shared cache key.

Mutation tests change one modeled input at a time and require the matching part
of the key, and so the key, to move. Refusal tests require a build with an
undeclared input to produce no key. End-to-end tests run `cache_build.sh` against
a real project and compare a cache hit with a clean build.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cache_closure  # noqa: E402
from cache_parity import differences, snapshot  # noqa: E402
from pipeline_fixture import AZAZEL_ROOT, Project, pipeline_available  # noqa: E402

PROJECT_CUE = """
options: [
	{name: "fancy", type: "bool", default: false},
	{name: "label", type: "string", default: "plain"},
	{name: "size", type: "u32", default: 4},
]

packages: {
	lib: {path: "deps/lib"}
	remote: {url: "https://example.invalid/remote.tar.gz", hash: "1220aaaa"}
}

system_deps: [{name: "python3", kind: "tool"}]

generated: {
	gen_tool: {
		tool: {root: "tools/gen/tool.zig", name: "gen"}
		args: [
			{kind: "input_file", value: "tools/gen/input.txt"},
			{kind: "output_file", value: "out.zig"},
		]
		stdin: "tools/gen/stdin.txt"
		outputs: [{name: "out.zig"}]
	}
	gen_py: {
		command: ["python3"]
		args: [
			{kind: "input_file", value: "tools/gen/script.py"},
			{kind: "output_file", value: "py.zig"},
		]
		outputs: [{name: "py.zig"}]
	}
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	profile: "release"
	install_dirs: [{source_dir: "assets", install_subdir: "share"}]
	pkg_imports: [{
		alias: "lib"
		package: "lib"
		module: "root"
		args: [{name: "mode", kind: "enum", value: "fast"}]
	}]
	native: {
		c_sources: ["native/add.c"]
		include_dirs: ["include"]
		object_files: ["native/prebuilt.o"]
		library_paths: ["libs"]
	}
	generated: [
		{from: "gen_tool", output: "out.zig", as: "import", alias: "gen_out"},
		{from: "gen_py", output: "py.zig", as: "import", alias: "py_out"},
	]
}
"""

FILES = {
    "src/main.zig": 'const util = @import("util.zig");\nconst data = @embedFile("data.txt");\nconst cfg = @import("cfg.zon");\npub fn main() void { _ = util; _ = data; _ = cfg; }\n',
    "src/util.zig": "pub const one = 1;\n",
    "src/data.txt": "data\n",
    "src/cfg.zon": ".{ .a = 1 }\n",
    "native/add.c": '#include "add.h"\n#include "other.h"\nint add(int a, int b) { return a + b; }\n',
    "native/add.h": "int add(int a, int b);\n",
    "native/other.h": "/* other */\n",
    "include/inc.h": "/* inc */\n",
    "native/prebuilt.o": "OBJ1",
    "libs/libx.a": "ARCHIVE1",
    "assets/a.txt": "asset",
    "tools/gen/tool.zig": 'const helper = @import("helper.zig");\npub fn main() void { _ = helper; }\n',
    "tools/gen/helper.zig": "pub const x = 1;\n",
    "tools/gen/input.txt": "input\n",
    "tools/gen/stdin.txt": "stdin\n",
    "tools/gen/script.py": "import sys\nopen(sys.argv[1], 'w').write('pub const x = 1;')\n",
}

TOOLS_AVAILABLE = pipeline_available()


def make_project(cue: str = PROJECT_CUE, files: dict[str, str] | None = None) -> Project:
    project = Project(cue)
    for name, text in {**FILES, **(files or {})}.items():
        project.write(name, text)
    project.add_package("lib", "pub fn build(b: *@import(\"std\").Build) void { _ = b; }\n", {"src/lib.zig": "pub const v = 1;\n"})
    return project


def fake_zig(directory: Path, name: str, version: str, marker: str = "") -> str:
    path = directory / name
    path.write_text(
        "#!/bin/sh\n"
        f"# {marker}\n"
        'case "$1" in\n'
        f"  version) echo {version} ;;\n"
        '  targets) echo \'.native = .{ .triple = "fake-native" }\' ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def append(project: Project, relative: str, text: str = "\n// edit\n") -> None:
    path = project.root / relative
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def replace(project: Project, relative: str, old: str, new: str) -> None:
    path = project.root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {relative}"
    path.write_text(text.replace(old, new), encoding="utf-8")


@unittest.skipUnless(TOOLS_AVAILABLE, "cue and zig are required")
class Mutations(unittest.TestCase):
    """Every modeled input moves the key, and moves the part that models it."""

    def setUp(self) -> None:
        self.project = make_project()
        self.addCleanup(self.project.close)

    def closure(self, args: list[str] | None = None, **kwargs) -> cache_closure.Closure:
        return cache_closure.compute(self.project.root, args, **kwargs)

    def assertMoves(self, part: str, mutate, args_before=None, args_after=None, **kwargs) -> None:
        before = self.closure(args_before, **kwargs)
        self.assertEqual(before.refusals, [], before.refusals)
        mutate()
        after = self.closure(args_after if args_after is not None else args_before, **kwargs)
        self.assertEqual(after.refusals, [], after.refusals)
        self.assertNotEqual(before.key, after.key, f"the key ignored a change to {part}")
        self.assertNotEqual(before.parts[part], after.parts[part], f"part {part!r} ignored the change")
        moved = sorted(name for name in before.parts if before.parts[name] != after.parts[name])
        self.assertIn(part, moved)

    def test_baseline_key_is_stable_and_relocatable(self) -> None:
        first = self.closure()
        self.assertEqual(first.refusals, [])
        self.assertEqual(first.key, self.closure().key)
        other = make_project()
        self.addCleanup(other.close)
        self.assertNotEqual(self.project.root, other.root)
        self.assertEqual(first.key, cache_closure.compute(other.root).key)

    def test_zig_sources(self) -> None:
        for name, relative in (
            ("module root", "src/main.zig"),
            ("imported source", "src/util.zig"),
            ("embedded file", "src/data.txt"),
            ("imported zon", "src/cfg.zon"),
        ):
            with self.subTest(name):
                self.assertMoves("sources", lambda r=relative: append(self.project, r))

    def test_native_sources_and_headers(self) -> None:
        for name, relative, part in (
            ("C source", "native/add.c", "headers"),
            ("header beside the source", "native/other.h", "headers"),
            ("header the source includes", "native/add.h", "headers"),
            ("file in an include directory", "include/inc.h", "headers"),
            ("object file", "native/prebuilt.o", "objects"),
            ("file in a library directory", "libs/libx.a", "objects"),
        ):
            with self.subTest(name):
                self.assertMoves(part, lambda r=relative: append(self.project, r, "more"))

    def test_installed_directories(self) -> None:
        self.assertMoves("installs", lambda: append(self.project, "assets/a.txt", "more"))
        self.assertMoves("installs", lambda: self.project.write("assets/b.txt", "new"))

    def test_new_file_in_include_directory(self) -> None:
        self.assertMoves("headers", lambda: self.project.write("include/new.h", "/* new */\n"))

    def test_generator_inputs(self) -> None:
        for name, relative in (
            ("tool root", "tools/gen/tool.zig"),
            ("tool import", "tools/gen/helper.zig"),
            ("input file", "tools/gen/input.txt"),
            ("stdin file", "tools/gen/stdin.txt"),
            ("interpreter script", "tools/gen/script.py"),
        ):
            with self.subTest(name):
                self.assertMoves("generated", lambda r=relative: append(self.project, r, "\n# edit\n" if r.endswith(".py") else "\n// edit\n"))

    def test_local_path_package(self) -> None:
        self.assertMoves("packages", lambda: append(self.project, "deps/lib/src/lib.zig"))
        self.assertMoves("packages", lambda: append(self.project, "deps/lib/build.zig"))
        self.assertMoves("packages", lambda: self.project.write("deps/lib/src/added.zig", "pub const y = 2;\n"))

    def test_fetched_package_identity(self) -> None:
        self.assertMoves("packages", lambda: replace(self.project, "project.cue", '"1220aaaa"', '"1220bbbb"'))
        self.assertMoves("packages", lambda: replace(self.project, "project.cue", "remote.tar.gz", "remote2.tar.gz"))

    def test_package_typed_args(self) -> None:
        self.assertMoves(
            "model",
            lambda: replace(self.project, "project.cue", 'args: [{name: "mode", kind: "enum", value: "fast"}]', 'args: [{name: "mode", kind: "enum", value: "fast"}, {name: "extra", kind: "bool", value: true}]'),
        )
        self.assertMoves("model", lambda: replace(self.project, "project.cue", 'value: "fast"', 'value: "small"'))
        self.assertMoves("model", lambda: replace(self.project, "project.cue", 'name: "mode", kind: "enum"', 'name: "mode", kind: "string"'))

    def test_target_cpu_and_abi(self) -> None:
        base = ["-Dtarget=x86_64-linux-musl"]
        self.assertMoves("target", lambda: None, base, ["-Dtarget=aarch64-linux-musl"])
        self.assertMoves("target", lambda: None, base, ["-Dtarget=x86_64-linux-gnu"])
        self.assertMoves("target", lambda: None, base, ["-Dtarget=x86_64-linux-musl", "-Dcpu=haswell"])
        self.assertMoves("target", lambda: None, base, [])

    def test_native_target_comes_from_the_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = fake_zig(Path(tmp), "zig-a", "0.15.2")
            b = fake_zig(Path(tmp), "zig-b", "0.15.2")
            Path(b).write_text(Path(b).read_text().replace("fake-native", "other-native"), encoding="utf-8")
            first = cache_closure.compute(self.project.root, zig=a)
            second = cache_closure.compute(self.project.root, zig=b)
        self.assertNotEqual(first.parts["target"], second.parts["target"])

    def test_options_and_build_arguments(self) -> None:
        self.assertMoves("options", lambda: None, [], ["-Dfancy=true"])
        self.assertMoves("options", lambda: None, ["-Dlabel=a"], ["-Dlabel=b"])
        self.assertMoves("options", lambda: None, ["-Dsize=4"], ["-Dsize=5"])
        self.assertMoves("options", lambda: None, [], ["-Dslice=app"])
        self.assertMoves("options", lambda: None, ["-Dslice=a"], ["-Dslice=a", "-Dslice=b"])
        self.assertMoves("options", lambda: None, [], ["-Dsubproject=x"])
        self.assertMoves("options", lambda: None, [], ["install"])

    def test_default_option_values_share_a_key(self) -> None:
        self.assertEqual(self.closure([]).key, self.closure(["-Dfancy=false", "-Dlabel=plain", "-Dsize=4"]).key)
        self.assertEqual(self.closure(["-Dfancy"]).key, self.closure(["-Dfancy=true"]).key)
        self.assertEqual(self.closure(["-Dslice=b", "-Dslice=a"]).key, self.closure(["-Dslice=a", "-Dslice=b"]).key)
        self.assertEqual(self.closure(["--summary", "all"]).key, self.closure([]).key)

    def test_optimize_and_build_model(self) -> None:
        self.assertMoves("model", lambda: replace(self.project, "project.cue", 'profile: "release"', 'profile: "debug"'))
        self.assertMoves("model", lambda: replace(self.project, "project.cue", 'name: "size", type: "u32", default: 4', 'name: "size", type: "u32", default: 8'))
        self.assertMoves("model", lambda: replace(self.project, "project.cue", 'kind: "exe"', 'kind: "static"'))

    def test_option_values_and_build_options(self) -> None:
        cue = PROJECT_CUE.replace(
            "profile: \"release\"",
            'profile: "release"\n\tbuild_options: ["fancy"]\n\toption_values: [{name: "v", kind: "u32", u32_value: 1}]',
        )
        self.project.write("project.cue", "package build\n\n" + cue)
        self.assertMoves("model", lambda: replace(self.project, "project.cue", "u32_value: 1", "u32_value: 2"))
        self.assertMoves("model", lambda: replace(self.project, "project.cue", 'build_options: ["fancy"]', 'build_options: ["label"]'))

    def test_engine_files(self) -> None:
        for relative in ("gen_build_spec.sh", "build.zig", "compat.zig", "schema.cue", "export.cue"):
            with self.subTest(relative):
                self.assertMoves("engine", lambda r=relative: append(self.project, r, "\n"))

    def test_toolchain_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = fake_zig(Path(tmp), "zig-old", "0.14.1")
            new = fake_zig(Path(tmp), "zig-new", "0.15.2")
            same_version = fake_zig(Path(tmp), "zig-same", "0.15.2", marker="rebuilt")
            a = cache_closure.compute(self.project.root, zig=old)
            b = cache_closure.compute(self.project.root, zig=new)
            c = cache_closure.compute(self.project.root, zig=same_version)
        self.assertNotEqual(a.parts["toolchain"], b.parts["toolchain"])
        self.assertNotEqual(b.parts["toolchain"], c.parts["toolchain"], "a different binary with the same version shares an identity")
        self.assertEqual(len({a.key, b.key, c.key}), 3)

    def test_system_dependency_declaration(self) -> None:
        self.assertMoves("system", lambda: replace(self.project, "project.cue", 'name: "python3", kind: "tool"', 'name: "python", kind: "tool"'))

    def test_interpreter_identity(self) -> None:
        before = self.closure()
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "python3"
            fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            saved = os.environ["PATH"]
            os.environ["PATH"] = tmp + os.pathsep + saved
            try:
                after = self.closure()
            finally:
                os.environ["PATH"] = saved
        self.assertNotEqual(before.key, after.key)
        self.assertNotEqual(before.parts["generated"], after.parts["generated"])


@unittest.skipUnless(TOOLS_AVAILABLE, "cue and zig are required")
class Refusals(unittest.TestCase):
    """A build with an input the key cannot name produces no key."""

    def refused(self, cue_edit=None, files=None, args=None, env=None, replace_cue=None) -> list[str]:
        cue = PROJECT_CUE
        if cue_edit:
            cue = cue.replace(*cue_edit)
        if replace_cue is not None:
            cue = replace_cue
        project = make_project(cue, files)
        self.addCleanup(project.close)
        merged = {**os.environ, **(env or {})}
        result = cache_closure.compute(project.root, args, env=merged)
        self.assertIsNone(result.key if result.refusals else None)
        return result.refusals

    def assertRefused(self, refusals: list[str], needle: str) -> None:
        self.assertTrue(any(needle in item for item in refusals), f"{needle!r} not in {refusals}")

    def test_the_fixture_itself_is_cacheable(self) -> None:
        self.assertEqual(self.refused(), [])

    def test_pre_and_post_commands(self) -> None:
        for field in ("pre", "post"):
            with self.subTest(field):
                refusals = self.refused(("profile: \"release\"", f'profile: "release"\n\t{field}: [{{argv: ["touch", "x"]}}]'))
                self.assertRefused(refusals, f"{field} commands")

    def test_command_generator_that_is_not_an_interpreter(self) -> None:
        refusals = self.refused(('command: ["python3"]', 'command: ["wayland-scanner"]'))
        self.assertRefused(refusals, "wayland-scanner")

    def test_interpreter_without_a_script(self) -> None:
        refusals = self.refused(("{kind: \"input_file\", value: \"tools/gen/script.py\"},", ""))
        self.assertRefused(refusals, "without a script")

    def test_environment_dependent_scripts(self) -> None:
        for name, body, reason in (
            ("environ", "import os\nx = os.environ['HOME']\n", "environment"),
            ("getenv", "import os\nx = os.getenv('HOME')\n", "environment"),
            ("clock", "import time\nx = time.time()\n", "clock"),
            ("network", "import socket\n", "network"),
            ("subprocess", "import subprocess\n", "other programs"),
        ):
            with self.subTest(name):
                refusals = self.refused(files={"tools/gen/script.py": body})
                self.assertRefused(refusals, reason)

    def test_environment_dependent_tool(self) -> None:
        for name, body, reason in (
            ("env", "pub fn main() void { _ = std.process.getEnvVarOwned; }", "environment"),
            ("clock", "pub fn main() void { _ = std.time.milliTimestamp(); }", "clock"),
            ("random", "pub fn main() void { _ = std.crypto.random; }", "randomness"),
        ):
            with self.subTest(name):
                refusals = self.refused(files={"tools/gen/tool.zig": body})
                self.assertRefused(refusals, reason)

    def test_environment_dependent_tool_import(self) -> None:
        refusals = self.refused(files={"tools/gen/helper.zig": "pub fn f() void { _ = std.time.timestamp(); }"})
        self.assertRefused(refusals, "clock")

    def test_system_libraries(self) -> None:
        for field in ("system_libs", "pkg_config_libs", "frameworks"):
            with self.subTest(field):
                refusals = self.refused(("object_files: [\"native/prebuilt.o\"]", f'object_files: ["native/prebuilt.o"]\n\t\t{field}: ["thing"]'))
                self.assertRefused(refusals, field)

    def test_system_paths_outside_the_project(self) -> None:
        refusals = self.refused(("library_paths: [\"libs\"]", 'library_paths: ["/usr/local/lib"]'))
        self.assertRefused(refusals, "/usr/local/lib")
        refusals = self.refused(("include_dirs: [\"include\"]", 'include_dirs: ["include"]\n\t\tsystem_include_dirs: ["/usr/include"]'))
        self.assertRefused(refusals, "/usr/include")

    def test_system_dependencies_other_than_tools(self) -> None:
        for kind in ("pkg_config", "library", "framework", "header", "include_dir"):
            with self.subTest(kind):
                refusals = self.refused(('{name: "python3", kind: "tool"}', f'{{name: "thing", kind: "{kind}"}}'))
                self.assertRefused(refusals, "host input")

    def test_libc_needs_a_fixed_abi(self) -> None:
        edit = ("object_files: [\"native/prebuilt.o\"]", 'object_files: ["native/prebuilt.o"]\n\t\tlink_libc: true')
        self.assertRefused(self.refused(edit), "links libc")
        self.assertRefused(self.refused(edit, args=["-Dtarget=aarch64-macos"]), "links libc")
        self.assertRefused(self.refused(edit, args=["-Dtarget=x86_64-linux"]), "links libc")
        project = make_project(PROJECT_CUE.replace(*edit))
        self.addCleanup(project.close)
        result = cache_closure.compute(project.root, ["-Dtarget=x86_64-linux-musl"])
        self.assertEqual(result.refusals, [])

    def test_redirecting_environment(self) -> None:
        for name in ("ZIG_LIB_DIR", "SDKROOT", "CPATH", "CC", "LIBRARY_PATH"):
            with self.subTest(name):
                self.assertRefused(self.refused(env={name: "/somewhere"}), name)

    def test_unmodeled_build_arguments(self) -> None:
        self.assertRefused(self.refused(args=["--prefix", "/tmp/x"]), "--prefix")
        self.assertRefused(self.refused(args=["--sysroot", "/x"]), "--sysroot")
        self.assertRefused(self.refused(args=["-Dundeclared=1"]), "-Dundeclared")
        self.assertRefused(self.refused(args=["-Doptimize=ReleaseFast"]), "-Doptimize")

    def test_declared_inputs_that_are_missing(self) -> None:
        project = make_project()
        self.addCleanup(project.close)
        (project.root / "native/prebuilt.o").unlink()
        (project.root / "tools/gen/input.txt").unlink()
        (project.root / "src/main.zig").unlink()
        result = cache_closure.compute(project.root)
        self.assertRefused(result.refusals, "native/prebuilt.o")
        self.assertRefused(result.refusals, "tools/gen/input.txt")
        self.assertRefused(result.refusals, "src/main.zig")

    def test_package_without_identity(self) -> None:
        refusals = self.refused(('hash: "1220aaaa"', 'hash: ""'))
        self.assertRefused(refusals, "neither a path nor a url")

    def test_missing_toolchain(self) -> None:
        project = make_project()
        self.addCleanup(project.close)
        result = cache_closure.compute(project.root, zig="/nonexistent/zig")
        self.assertIsNone(result.key)
        self.assertTrue(result.refusals)

    def test_toolchain_outside_declared_lanes(self) -> None:
        project = make_project(PROJECT_CUE + '\ntoolchain: zig: {lanes: ["0.16"], preferred: "0.16"}\n')
        self.addCleanup(project.close)
        with tempfile.TemporaryDirectory() as tmp:
            zig = fake_zig(Path(tmp), "zig", "0.14.1")
            result = cache_closure.compute(project.root, zig=zig)
        self.assertRefused(result.refusals, "outside the declared lanes")


@unittest.skipUnless(TOOLS_AVAILABLE, "cue and zig are required")
class CacheScripts(unittest.TestCase):
    """cache_build.sh and cache_key.sh against a project that really builds."""

    CUE = """
app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	deps: ["lib"]
}

lib: #Module & {
	kind: "static"
	root: "src/lib.zig"
	native: {
		c_sources: ["native/add.c"]
		include_dirs: ["native"]
	}
}
"""

    def setUp(self) -> None:
        self.project = Project(self.CUE, modules=("app", "lib"))
        self.addCleanup(self.project.close)
        self.project.write("src/main.zig", 'const std = @import("std");\npub fn main() void { std.debug.print("hi\\n", .{}); }\n')
        self.project.write("src/lib.zig", "pub export fn two() u32 { return 2; }\n")
        self.project.write("native/add.c", '#include "add.h"\nint add(int a, int b) { return a + b; }\n')
        self.project.write("native/add.h", "int add(int a, int b);\n")
        self.store = Path(tempfile.mkdtemp(prefix="azazel-store-"))
        self.addCleanup(shutil.rmtree, self.store, ignore_errors=True)

    def cache_build(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            AZAZEL_PROJECT=str(self.project.root),
            SHARED=str(self.store),
            ZIG_LOCAL_CACHE_DIR=str(self.project.root / ".zig-cache"),
            **(env or {}),
        )
        environment.pop("AZAZEL_EXPERIMENTAL_CACHE", None)
        return subprocess.run(
            ["sh", str(AZAZEL_ROOT / "cache_build.sh"), *args],
            cwd=self.project.root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def wipe(self) -> None:
        for name in ("zig-out", ".zig-cache"):
            shutil.rmtree(self.project.root / name, ignore_errors=True)

    def clean_build(self) -> dict[str, str]:
        self.wipe()
        built = self.project.zig_build()
        self.assertEqual(built.returncode, 0, built.stdout)
        return snapshot(self.project.root / "zig-out")

    def test_no_experimental_gate(self) -> None:
        text = (AZAZEL_ROOT / "cache_build.sh").read_text(encoding="utf-8")
        self.assertNotIn("AZAZEL_EXPERIMENTAL_CACHE", text)
        result = self.cache_build()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_miss_then_hit_matches_a_clean_build(self) -> None:
        clean = self.clean_build()
        self.assertTrue(clean)
        # Some toolchains do not produce the same bytes from two clean builds
        # of one source. A hit can only be held to a clean build when they do.
        again = self.clean_build()
        repeatable = differences(clean, again) == []
        if not repeatable:
            print(f"\nclean builds differ on this host: {differences(clean, again)}", file=sys.stderr)
        self.wipe()
        first = self.cache_build()
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertIn("MISS", first.stdout)
        miss = snapshot(self.project.root / "zig-out", normalize=False)
        self.wipe()
        second = self.cache_build()
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn("HIT", second.stdout)
        hit = snapshot(self.project.root / "zig-out", normalize=False)
        self.assertEqual(differences(miss, hit), [])
        self.assertEqual(sorted(hit), sorted(clean))
        if repeatable:
            self.assertEqual(differences(clean, snapshot(self.project.root / "zig-out")), [])
        self.assertFalse((self.project.root / "zig-out" / ".azazel-cache-key").exists())

    def test_native_source_change_misses(self) -> None:
        self.assertIn("MISS", self.cache_build().stdout)
        self.assertIn("HIT", self.cache_build().stdout)
        self.project.write("native/add.c", '#include "add.h"\nint add(int a, int b) { return a + b + 1; }\n')
        result = self.cache_build()
        self.assertIn("MISS", result.stdout)
        self.assertIn("HIT", self.cache_build().stdout)

    def test_header_change_misses(self) -> None:
        self.assertIn("MISS", self.cache_build().stdout)
        append(self.project, "native/add.h", "/* changed */\n")
        self.assertIn("MISS", self.cache_build().stdout)

    def test_target_change_misses(self) -> None:
        self.assertIn("MISS", self.cache_build("-Dtarget=x86_64-linux-musl").stdout)
        self.assertIn("MISS", self.cache_build("-Dtarget=aarch64-linux-musl").stdout)
        self.assertIn("HIT", self.cache_build("-Dtarget=x86_64-linux-musl").stdout)

    def test_refused_build_touches_nothing(self) -> None:
        self.project.write("project.cue", "package build\n\n" + self.CUE.replace('deps: ["lib"]', 'deps: ["lib"]\n\tpost: [{argv: ["true"]}]'))
        result = self.cache_build()
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("not cacheable", result.stdout)
        self.assertEqual(list(self.store.iterdir()), [])
        self.assertFalse((self.project.root / "zig-out").exists())

    def test_entry_stored_under_another_key_is_refused(self) -> None:
        self.assertIn("MISS", self.cache_build().stdout)
        stored = next(self.store.iterdir())
        key = stored.stem
        # Move the entry under the key of a different build.
        other = self.project.root
        append(self.project, "native/add.h", "/* other */\n")
        other_key = subprocess.run(
            ["sh", str(AZAZEL_ROOT / "cache_key.sh")],
            cwd=other,
            env={**os.environ, "AZAZEL_PROJECT": str(other)},
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        self.assertNotEqual(key, other_key)
        shutil.copy2(stored, self.store / f"{other_key}.tar")
        result = self.cache_build()
        self.assertIn("does not carry key", result.stdout)
        self.assertIn("MISS", result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_cache_key_script_prints_key_or_reasons(self) -> None:
        env = {**os.environ, "AZAZEL_PROJECT": str(self.project.root)}
        ok = subprocess.run(["sh", str(AZAZEL_ROOT / "cache_key.sh")], env=env, text=True, capture_output=True, check=False)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertRegex(ok.stdout.strip(), r"^[0-9a-f]{64}$")
        explained = subprocess.run(["sh", str(AZAZEL_ROOT / "cache_key.sh"), "--explain"], env=env, text=True, capture_output=True, check=False)
        self.assertIn('"parts"', explained.stdout)
        bad = subprocess.run(["sh", str(AZAZEL_ROOT / "cache_key.sh"), "--prefix", "/x"], env=env, text=True, capture_output=True, check=False)
        self.assertEqual(bad.returncode, 3)
        self.assertEqual(bad.stdout, "")


@unittest.skipUnless(
    os.environ.get("AZAZEL_CACHE_PARITY_ROOT"),
    "set AZAZEL_CACHE_PARITY_ROOT to a corpus clone directory to compare cache hits with clean builds on real slices",
)
class RealSlices(unittest.TestCase):
    """Cache-hit artifacts equal clean-build artifacts on the libvaxis and libxev slices."""

    def test_hit_matches_clean_build(self) -> None:
        import cache_parity
        import huge_corpus

        huge_corpus.FETCH_TOOLCHAINS = os.environ.get("AZAZEL_CACHE_PARITY_FETCH") == "1"
        root = Path(os.environ["AZAZEL_CACHE_PARITY_ROOT"])
        for repo in huge_corpus.select_repos(["libvaxis", "libxev"]):
            with self.subTest(repo.name), tempfile.TemporaryDirectory(prefix="azazel-parity-") as tmp:
                entry = cache_parity.parity_entry(root, repo, Path(tmp))
                self.assertTrue(entry["passed"], entry)


class ParityNormalization(unittest.TestCase):
    def test_non_macho_files_hash_as_is(self) -> None:
        from cache_parity import normalized_digest
        import hashlib

        self.assertEqual(normalized_digest(b"abc"), hashlib.sha256(b"abc").hexdigest())

    def test_snapshot_reports_differences(self) -> None:
        self.assertEqual(differences({"a": "1"}, {"a": "1"}), [])
        self.assertEqual(differences({"a": "1", "b": "2"}, {"a": "2", "c": "3"}), ["only in first: b", "only in second: c", "differs: a"])


if __name__ == "__main__":
    unittest.main()
