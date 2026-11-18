"""Tests for build.zig.zon parsing, dependency metadata and failure diagnosis."""

from __future__ import annotations

import functools
import hashlib
import http.server
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_deps  # noqa: E402
import huge_corpus  # noqa: E402
import zig_toolchain  # noqa: E402
import zon  # noqa: E402
from pipeline_fixture import Project, pipeline_available, zon_text  # noqa: E402

# The dependency block of the ZLS fork's build.zig.zon, with its comments.
ZLS_ZON = """.{
    .name = .zls,
    // Remove `-dev` when tagging a new ZLS release.
    .version = "0.17.0-dev",
    .minimum_zig_version = "0.17.0-dev.292+fc1c83a36",
    .dependencies = .{
        .known_folders = .{
            .url = "https://github.com/ziglibs/known-folders/archive/207c34a16e4365edc20d92c7892f962b3bed46e8.tar.gz",
            .hash = "known_folders-0.0.0-Fy-PJsbKAACbDh9bBxR0MMThxZSS6A9RH4apWphNHY70",
        },
        .lsp_kit = .{
            .url = "https://github.com/zigtools/lsp-kit/archive/b886a2b0d5cee85ecbcc3089b863f7517cc9ff7f.tar.gz",
            .hash = "lsp_kit-0.1.0-bi_PL3IyDACfp1xdTnkiOHEok2YpPCCCJHuuOcNzjl1D",
        },
        .tracy = .{
            .url = "https://github.com/wolfpld/tracy/archive/refs/tags/v0.13.1.tar.gz",
            .hash = "N-V-__8AAOncKwEm1F9c5LrT7HMNmRMYX8-fAoqpc6YyTu9X",
            .lazy = true,
        },
    },
    .paths = .{""},
    .fingerprint = 0xa66330b97eb969ae, // Changing this has security and trust implications.
}
"""

# From the Capy fork: a zip pinned with a pre-0.14 hash, and a git dependency.
CAPY_ZON = """.{
    .name = .capy,
    .fingerprint = 0x4724968847bbbb92,
    .version = "0.4.1",
    .minimum_zig_version = "0.14.1",
    .dependencies = .{
        .@"zig-objc" = .{
            .url = "https://github.com/mitchellh/zig-objc/archive/362d12f4d91dfde84668e0befc5a8ca76659965a.zip",
            .hash = "12206038da3a8d42de25babfadaa3b8fb01c223850a1f1ce309034172d150df61a8c",
            .lazy = true,
        },
        .zigimg = .{
            .url = "git+https://github.com/zigimg/zigimg#74caab5edd7c5f1d2f7d87e5717435ce0f0affa1",
            .hash = "zigimg-0.1.0-8_eo2nWlEgCddu8EGLOM_RkYshx3sC8tWv-yYA4-htS6",
        },
        .local = .{ .path = "vendor/local" },
    },
    .paths = .{""},
}
"""

CAPY_BUILD = """
pub fn build(b: *std.Build) !void {
    const zigimg_dep = b.dependency("zigimg", .{
        .target = target,
        .optimize = optimize,
    });
    const zigimg = zigimg_dep.module("zigimg");
    module.addImport("zigimg", zigimg);
    if (b.lazyDependency("zig-objc", .{ .target = target })) |objc| {
        module.addImport("objc", objc.module("objc"));
    }
    const helper = b.dependency("local", .{}).artifact("helper");
    _ = helper;
}
"""


class Parser(unittest.TestCase):
    def test_scalars_and_structs(self) -> None:
        value = zon.parse('.{ .a = 1, .b = 0x10, .c = -2, .d = 1.5, .e = true, .f = null, .g = .tag, .h = "s" }')
        self.assertEqual(value, {"a": 1, "b": 16, "c": -2, "d": 1.5, "e": True, "f": None, "g": "tag", "h": "s"})
        self.assertIsInstance(value["g"], zon.EnumLiteral)

    def test_tuples_nested_structs_and_trailing_commas(self) -> None:
        self.assertEqual(zon.parse('.{ "a", "b", }'), ["a", "b"])
        self.assertEqual(zon.parse(".{ .x = .{ .y = .{ 1, 2 } } }"), {"x": {"y": [1, 2]}})
        self.assertEqual(zon.parse(".{}"), {})

    def test_strings(self) -> None:
        self.assertEqual(zon.parse(r'"a\n\"b\"\x41\u{1F600}\\"'), 'a\n"b"A\U0001F600\\')
        self.assertEqual(zon.parse('.{ .text =\n    \\\\line one\n    \\\\line two\n    ,\n}'), {"text": "line one\nline two"})

    def test_comments_and_quoted_names(self) -> None:
        text = '.{ // c1\n .@"zig-objc" = .{ .url = "http://x/y//z" }, // not a comment inside the string\n .v = .@"odd name" }'
        self.assertEqual(zon.parse(text), {"zig-objc": {"url": "http://x/y//z"}, "v": "odd name"})

    def test_errors_carry_a_location(self) -> None:
        with self.assertRaises(zon.ZonError) as ctx:
            zon.parse('.{\n    .a = 1,\n    .b = ,\n}')
        self.assertEqual((ctx.exception.line, ctx.exception.column), (3, 10))
        for bad in ('.{ .a = 1 .b = 2 }', '.{ .a = 1, .a = 2 }', '.{ .a = 1, 2 }', '"open', ".{} extra"):
            with self.assertRaises(zon.ZonError, msg=bad):
                zon.parse(bad)


class Dependencies(unittest.TestCase):
    def test_reads_names_urls_hashes_paths_and_lazy_flags(self) -> None:
        deps = zon.read_dependencies(ZLS_ZON)
        self.assertEqual([dep.alias for dep in deps], ["known_folders", "lsp_kit", "tracy"])
        tracy = deps[2]
        self.assertEqual(tracy.url, "https://github.com/wolfpld/tracy/archive/refs/tags/v0.13.1.tar.gz")
        self.assertEqual(tracy.hash, "N-V-__8AAOncKwEm1F9c5LrT7HMNmRMYX8-fAoqpc6YyTu9X")
        self.assertTrue(tracy.lazy)
        self.assertFalse(deps[0].lazy)

    def test_source_and_hash_format(self) -> None:
        objc, zigimg, local = zon.read_dependencies(CAPY_ZON)
        self.assertEqual((objc.alias, objc.source, objc.hash_format), ("zig-objc", "zip", "legacy-multihash"))
        self.assertEqual((zigimg.source, zigimg.hash_format), ("git", "name-version"))
        self.assertEqual(zigimg.git_ref, "74caab5edd7c5f1d2f7d87e5717435ce0f0affa1")
        self.assertEqual((local.source, local.hash_format, local.path), ("path", "none", "vendor/local"))
        tracy = zon.read_dependencies(ZLS_ZON)[2]
        self.assertEqual((tracy.source, tracy.hash_format), ("tarball", "nameless"))

    def test_alias_can_differ_from_package_name(self) -> None:
        dep = zon.Dependency(alias="vulkan_zig", url="https://x/v.tar.gz", hash="vulkan-0.0.0-r7Ytx-lrAwDA6o57xnZ2Fs7AGKNBEkyGgsfQKyBlJw-2")
        self.assertEqual((dep.package_name, dep.package_version), ("vulkan", "0.0.0"))
        dev = zon.Dependency(alias="zmath", hash="zmath-0.11.0-dev-wjwivdMsAwD-xaLj76YHUq3t9JDH-X16xuMTmnDzqbu2")
        self.assertEqual((dev.package_name, dev.package_version), ("zmath", "0.11.0-dev"))
        self.assertEqual(dev.manifest()["alias"], "zmath")

    def test_dependency_lines(self) -> None:
        lines = zon.dependency_lines(ZLS_ZON)
        self.assertEqual(lines["known_folders"], (7, 10))
        self.assertEqual(lines["tracy"], (15, 19))

    def test_rewrite_touches_only_the_dependencies(self) -> None:
        deps = zon.read_dependencies(CAPY_ZON)
        changed = [deps[1], zon.Dependency(alias="new-dep", path="../new", lazy=True)]
        text = zon.replace_dependencies(CAPY_ZON, changed)
        self.assertEqual(zon.read_dependencies(text), changed)
        self.assertIn('.@"new-dep" = .{', text)
        self.assertIn(".fingerprint = 0x4724968847bbbb92,", text)
        self.assertTrue(text.endswith('    .paths = .{""},\n}\n'))
        self.assertEqual(zon.replace_dependencies(text, deps).count("zig-objc"), 2)
        self.assertEqual(zon.parse(zon.replace_dependencies(CAPY_ZON, []))["dependencies"], {})

    def test_diff_explains_each_difference(self) -> None:
        actual = zon.read_dependencies(CAPY_ZON)
        declared = [
            zon.Dependency(alias="zigimg", url=actual[1].url, hash="zigimg-0.1.0-other"),
            zon.Dependency(alias="extra", path="x"),
        ]
        problems = zon.diff_dependencies(declared, actual)
        self.assertIn("package 'extra' is declared in project.cue but missing from build.zig.zon", problems)
        self.assertTrue(any(p.startswith("package 'zigimg' hash differs") for p in problems))
        self.assertIn("dependency 'zig-objc' is in build.zig.zon but not declared in project.cue packages", problems)
        self.assertEqual(zon.diff_dependencies(actual, actual), [])

    def test_cue_round_trip(self) -> None:
        deps = zon.read_dependencies(CAPY_ZON)
        cue = zon.render_cue_packages(deps)
        self.assertIn('"zig-objc": {', cue)
        self.assertIn("lazy: true", cue)
        exported = {dep.alias: {k: v for k, v in (("url", dep.url), ("hash", dep.hash), ("path", dep.path), ("lazy", dep.lazy)) if v} for dep in deps}
        self.assertEqual(zon.from_packages(exported), deps)


class CorpusMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "build.zig.zon").write_text(CAPY_ZON)
        (self.repo / "build.zig").write_text(CAPY_BUILD)
        self.info = corpus_deps.describe(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def entry(self, alias: str) -> dict[str, object]:
        return next(item for item in self.info["dependencies"] if item["alias"] == alias)

    def test_manifest_fields(self) -> None:
        self.assertEqual(self.info["minimum_zig_version"], "0.14.1")
        self.assertEqual(self.info["summary"]["count"], 3)
        self.assertEqual(self.info["summary"]["lazy"], 1)
        self.assertEqual(self.info["summary"]["by_source"], {"git": 1, "path": 1, "zip": 1})
        self.assertEqual(self.info["summary"]["by_hash_format"], {"legacy-multihash": 1, "name-version": 1, "none": 1})

    def test_package_modules_and_import_aliases(self) -> None:
        self.assertEqual(self.entry("zigimg")["modules"], ["zigimg"])
        self.assertEqual(self.entry("zigimg")["import_aliases"], ["zigimg"])
        # The dependency is named zig-objc, its module objc, and it is imported as objc.
        self.assertEqual(self.entry("zig-objc")["modules"], ["objc"])
        self.assertEqual(self.entry("zig-objc")["import_aliases"], ["objc"])
        self.assertEqual(self.entry("local")["artifacts"], ["helper"])

    def test_nested_path_packages_are_walked(self) -> None:
        # A workspace: the root reaches a zip only through two path packages.
        (self.repo / "build.zig.zon").write_text(zon_text("ws", {"port": {"path": "port/pico"}, "outside": {"path": "../elsewhere"}}))
        (self.repo / "port" / "pico").mkdir(parents=True)
        (self.repo / "port" / "pico" / "build.zig.zon").write_text(
            zon_text("pico", {"net": {"path": "../../modules/net"}, "root": {"path": "../.."}})
        )
        (self.repo / "modules" / "net").mkdir(parents=True)
        (self.repo / "modules" / "net" / "build.zig.zon").write_text(
            zon_text("net", {"lwip": {"url": "https://example.org/lwip/STABLE-2_1_3.zip", "hash": "N-V-__8AAlwip"}})
        )
        info = corpus_deps.describe(self.repo)
        self.assertEqual(info["summary"]["count"], 2)
        nested = {entry["alias"]: entry for entry in info["nested_dependencies"]}
        self.assertEqual(sorted(nested), ["lwip", "net", "root"])
        self.assertEqual(nested["lwip"]["via"], ["port", "net"])
        self.assertEqual(nested["lwip"]["manifest"], "modules/net/build.zig.zon")
        self.assertEqual(nested["lwip"]["source"], "zip")
        self.assertEqual(info["summary"]["nested_by_source"], {"path": 2, "zip": 1})

        # The MicroZig shape: no location, and the only zip is nested.
        diagnosis = corpus_deps.diagnose("error: failed to create temporary zip file: AccessDenied\n", info, self.repo)
        self.assertEqual(diagnosis["dependency"], "lwip")
        self.assertEqual(diagnosis["via"], ["port", "net"])
        self.assertIn("reached through port -> net", diagnosis["explanation"])

        # An error on a line of the nested manifest maps to the entry there.
        first = nested["lwip"]["manifest_lines"][0]
        located = f"{self.repo}/modules/net/build.zig.zon:{first + 1}:20: error: bad HTTP response code: '404 Not Found'\n"
        diagnosis = corpus_deps.diagnose(located, info, self.repo)
        self.assertEqual((diagnosis["dependency"], diagnosis["manifest"]), ("lwip", "modules/net/build.zig.zon"))

    def test_repo_without_a_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            info = corpus_deps.describe(Path(empty))
        self.assertIsNone(info["manifest"])
        self.assertEqual(info["dependencies"], [])

    def test_unreadable_manifest_is_reported(self) -> None:
        (self.repo / "build.zig.zon").write_text(".{ .dependencies = .{ .a = } }")
        info = corpus_deps.describe(self.repo)
        self.assertIn("build.zig.zon: 1:28: expected a value", info["error"])

    def test_overlay_records_the_metadata(self) -> None:
        huge_corpus.write_overlay(self.repo, huge_corpus.select_repos(["capy"])[0])
        corpus = json.loads((self.repo / ".azazel" / "corpus.json").read_text())
        self.assertEqual(corpus["dependencies"]["dependencies"][0]["alias"], "zig-objc")
        self.assertEqual(corpus["dependencies"]["dependencies"][0]["hash_format"], "legacy-multihash")
        self.assertTrue((self.repo / ".azazel" / "dependencies.json").is_file())

    def test_format_failure_in_a_fetched_package_names_the_dependency(self) -> None:
        # Shape of the Capy failure: the error is inside the fetched zig-objc.
        output = (
            "/roots/a/.zig-cache-capy-0.14.1/p/12206038da3a8d42de25babfadaa3b8fb01c223850a1f1ce309034172d150df61a8c/"
            "build.zig.zon:2:13: error: name must be a valid bare zig identifier (hint: switch from string to enum literal)\n"
            '    .name = "zig-objc",\n'
        )
        self.assertEqual(huge_corpus.classify_failure(output, 1), "dependency-format")
        diagnosis = corpus_deps.diagnose(output, self.info, self.repo)
        self.assertEqual((diagnosis["kind"], diagnosis["reason"]), ("format", "legacy-name"))
        self.assertEqual(diagnosis["dependency"], "zig-objc")
        self.assertEqual(diagnosis["hash_format"], "legacy-multihash")
        self.assertFalse(diagnosis["transitive"])
        self.assertIn("dependency zig-objc (zip, https://github.com/mitchellh/zig-objc/", diagnosis["explanation"])

    def test_format_failure_in_a_freshly_unpacked_package_names_the_dependency(self) -> None:
        # The real output of `zig build` in the Capy fork on Zig 0.14.1.
        output = (
            "<root>/.zig-cache-capy-0.14.1/tmp/<random>/zig-objc-362d12f4d91dfde84668e0befc5a8ca76659965a/"
            "build.zig.zon:2:13: error: name must be a valid bare zig identifier (hint: switch from string to enum literal)\n"
            '    .name = "zig-objc",\n'
            "            ^~~~~~~~~~\n"
        )
        diagnosis = corpus_deps.diagnose(output, self.info, self.repo)
        self.assertEqual(diagnosis["dependency"], "zig-objc")
        self.assertEqual(diagnosis["package_dir"], "zig-objc-362d12f4d91dfde84668e0befc5a8ca76659965a")
        self.assertFalse(diagnosis["transitive"])
        self.assertEqual(diagnosis["source"], "zip")

        other = output.replace("zig-objc-362d12f4d91dfde84668e0befc5a8ca76659965a", "something-else-1.0")
        diagnosis = corpus_deps.diagnose(other, self.info, self.repo)
        self.assertEqual(diagnosis["dependency"], "")
        self.assertTrue(diagnosis["transitive"])

    def test_unpack_directories_are_stable_in_stored_output(self) -> None:
        repo = huge_corpus.select_repos(["capy"])[0]
        text = "/r/.zig-cache-capy-0.14.1/tmp/5476af0fb9250590/zig-objc-362d/build.zig.zon:2:13: error: x"
        self.assertEqual(
            huge_corpus.portable_text(text, Path("/r"), repo),
            "<root>/.zig-cache-capy-0.14.1/tmp/<random>/zig-objc-362d/build.zig.zon:2:13: error: x",
        )

    def test_format_failure_in_an_unlisted_package_is_transitive(self) -> None:
        output = (
            "/roots/a/.zig-cache/p/N-V-__8AAunknownpackage/build.zig.zon:1:2: error: "
            "missing top-level 'fingerprint' field; suggested value: 0xda946e2ce6d0d262\n"
        )
        diagnosis = corpus_deps.diagnose(output, self.info, self.repo)
        self.assertEqual(diagnosis["reason"], "missing-fingerprint")
        self.assertTrue(diagnosis["transitive"])
        self.assertEqual(diagnosis["package_hash"], "N-V-__8AAunknownpackage")
        self.assertEqual(diagnosis["dependency"], "")

    def test_fetch_failure_on_a_manifest_line_names_the_dependency(self) -> None:
        output = f"{self.repo}/build.zig.zon:13:20: error: bad HTTP response code: '404 Not Found'\n"
        self.assertEqual(huge_corpus.classify_failure(output, 1), "dependency-fetch")
        diagnosis = corpus_deps.diagnose(output, self.info, self.repo)
        self.assertEqual((diagnosis["kind"], diagnosis["reason"], diagnosis["dependency"]), ("fetch", "http-status", "zigimg"))
        self.assertEqual(diagnosis["line"], 13)

    def test_zip_failure_without_a_location_offers_the_zip_dependencies(self) -> None:
        # Shape of the MicroZig failure.
        output = "error: failed to create temporary zip file: AccessDenied\n"
        self.assertEqual(huge_corpus.classify_failure(output, 1), "dependency-fetch")
        diagnosis = corpus_deps.diagnose(output, self.info, self.repo)
        self.assertEqual(diagnosis["reason"], "zip-temp-file")
        self.assertEqual(diagnosis["candidates"], ["zig-objc"])
        self.assertEqual(diagnosis["dependency"], "zig-objc")

    def test_fetch_and_format_are_distinct(self) -> None:
        cases = {
            "x/build.zig.zon:1:1: error: unable to connect to server: ConnectionRefused": "dependency-fetch",
            "x/build.zig.zon:1:1: error: hash mismatch: manifest declares a but the fetched package has b": "dependency-fetch",
            "x/build.zig.zon:1:1: error: invalid hash: incomplete": "dependency-format",
            "x/build.zig.zon:1:1: error: dependency is missing hash field": "dependency-format",
            "x/build.zig.zon:1:12: error: expected enum literal": "dependency-format",
            "x/build.zig.zon:1:1: error: invalid fingerprint: 0x1; if this is a new or forked package, use this value: 0x2": "dependency-format",
        }
        for output, expected in cases.items():
            self.assertEqual(huge_corpus.classify_failure(output, 1), expected, output)
        self.assertIsNone(corpus_deps.diagnose("src/main.zig:1:1: error: expected enum literal", self.info, self.repo))
        self.assertEqual(huge_corpus.classify_failure("src/main.zig:1:1: error: expected enum literal", 1), "unknown")


def package_tarball(name: str) -> bytes:
    buffer = io.BytesIO()
    files = {
        "build.zig": 'const std = @import("std");\npub fn build(b: *std.Build) void {\n    _ = b;\n}\n',
        "build.zig.zon": zon_text(name, paths=("build.zig", "build.zig.zon")),
    }
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{name}/{path}")
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


@unittest.skipUnless(shutil.which("zig"), "needs zig on PATH")
class RealZigFailures(unittest.TestCase):
    """Run the real `zig build` against broken manifests from two clone roots."""

    CONSUMER_BUILD = 'const std = @import("std");\npub fn build(b: *std.Build) void {\n    _ = b.dependency("dep", .{});\n}\n'
    GOOD_HASH = "good-0.0.0-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.site = self.base / "site"
        self.site.mkdir()
        (self.site / "good.tar.gz").write_bytes(package_tarball("good"))
        handler = functools.partial(QuietHandler, directory=str(self.site))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

        version = zig_toolchain.zig_version_of(shutil.which("zig"))
        self.repo = huge_corpus.Repo(
            "fixture", "example/fixture", "example/fixture", "test fixture", version[:4],
            ("zig", "build", "--help"), version, ("zig", "build"), "dependency-fetch",
            ("azazel", "parity"), "ok", ("exe:fixture",),
        )
        self.saved_env = dict(os.environ)
        os.environ[self.repo.required_toolchain().env_key] = shutil.which("zig")
        for key in ("ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR"):
            os.environ.pop(key, None)
        huge_corpus._RESOLUTIONS.clear()
        self.saved = (huge_corpus.ensure_clone, huge_corpus.PACKAGE_CACHE)
        huge_corpus.ensure_clone = lambda root, repo: root / repo.name

    def tearDown(self) -> None:
        huge_corpus.ensure_clone, huge_corpus.PACKAGE_CACHE = self.saved
        os.environ.clear()
        os.environ.update(self.saved_env)
        huge_corpus._RESOLUTIONS.clear()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def build(self, root_name: str, dependency: dict[str, object]) -> dict[str, object]:
        root = self.base / root_name
        clone = root / "fixture"
        clone.mkdir(parents=True)
        (clone / "build.zig").write_text(self.CONSUMER_BUILD)
        (clone / "build.zig.zon").write_text(
            zon_text("fixture", {"other": {"path": "vendor/other"}, "dep": dependency}, paths=("build.zig", "build.zig.zon"))
        )
        huge_corpus.run_build(root, [self.repo])
        return json.loads((root / "build-results.json").read_text())[0]

    def stable(self, entry: dict[str, object]) -> tuple[object, ...]:
        diagnosis = entry["dependency_diagnosis"]
        return (entry["classification"], diagnosis, entry["cache_roots"], entry["command"][1:], entry["dependencies"])

    def assert_same_from_two_roots(self, dependency: dict[str, object]) -> dict[str, object]:
        first = self.build("root-one", dependency)
        second = self.build("another/deeper/root-two", dependency)
        self.assertEqual(self.stable(first), self.stable(second))
        for entry in (first, second):
            self.assertNotIn(str(self.base), entry["output"])
            self.assertIn("<root>/fixture/build.zig.zon", entry["output"])
        return first

    def test_unreachable_host_is_a_fetch_failure(self) -> None:
        entry = self.assert_same_from_two_roots({"url": "http://127.0.0.1:9/good.tar.gz", "hash": self.GOOD_HASH})
        self.assertEqual(entry["classification"], "dependency-fetch")
        diagnosis = entry["dependency_diagnosis"]
        self.assertEqual((diagnosis["dependency"], diagnosis["reason"]), ("dep", "connection"))
        self.assertEqual(diagnosis["url"], "http://127.0.0.1:9/good.tar.gz")
        self.assertEqual(entry["cache_roots"]["packages"], "<root>/.zig-cache-fixture-" + self.repo.build_zig + "/p")

    def test_missing_archive_is_a_fetch_failure(self) -> None:
        entry = self.build("root", {"url": f"{self.url}/missing.tar.gz", "hash": self.GOOD_HASH})
        self.assertEqual(entry["classification"], "dependency-fetch")
        self.assertEqual(entry["dependency_diagnosis"]["reason"], "http-status")
        self.assertEqual(entry["dependency_diagnosis"]["dependency"], "dep")

    def test_wrong_hash_is_a_fetch_failure_with_its_own_reason(self) -> None:
        entry = self.build("root", {"url": f"{self.url}/good.tar.gz", "hash": self.GOOD_HASH})
        self.assertEqual(entry["classification"], "dependency-fetch")
        self.assertEqual(entry["dependency_diagnosis"]["reason"], "hash-mismatch")

    def test_url_without_a_hash_is_a_format_failure(self) -> None:
        entry = self.assert_same_from_two_roots({"url": f"{self.url}/good.tar.gz"})
        self.assertEqual(entry["classification"], "dependency-format")
        diagnosis = entry["dependency_diagnosis"]
        self.assertEqual((diagnosis["kind"], diagnosis["reason"], diagnosis["dependency"]), ("format", "missing-hash", "dep"))

    def test_shared_package_cache_is_reported(self) -> None:
        huge_corpus.PACKAGE_CACHE = self.base / "shared-cache"
        entry = self.build("root", {"url": "http://127.0.0.1:9/good.tar.gz", "hash": self.GOOD_HASH})
        self.assertTrue(entry["cache_roots"]["shared_package_cache"])
        self.assertEqual(entry["cache_roots"]["global"], "<package-cache>")
        self.assertEqual(entry["cache_roots"]["packages"], "<package-cache>/p")
        self.assertEqual(entry["cache_roots"]["local"], "<root>/.zig-cache-local-fixture-" + self.repo.build_zig)
        self.assertTrue((self.base / "shared-cache").is_dir())


MATHS_BUILD = (
    'const std = @import("std");\n\n'
    "pub fn build(b: *std.Build) void {\n"
    '    _ = b.addModule("maths", .{ .root_source_file = b.path("src/maths.zig") });\n'
    "}\n"
)

MATHS_PROJECT = """
packages: maths: {
	path: "deps/maths"
	lazy: %s
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	pkg_imports: [{alias: "m", package: "maths", module: "maths", pass_target: false, pass_optimize: false}]
}
"""


@unittest.skipUnless(pipeline_available(), "needs cue and zig on PATH")
class ProjectPackages(unittest.TestCase):
    """A project.cue package reaches build.zig.zon and a module imports it."""

    def project(self, lazy: bool = False) -> Project:
        project = Project(MATHS_PROJECT % ("true" if lazy else "false"))
        self.addCleanup(project.close)
        project.add_package("maths", MATHS_BUILD, {"src/maths.zig": "pub const answer: u8 = 42;\n"})
        project.write("src/main.zig", 'pub fn main() u8 {\n    return @import("m").answer;\n}\n')
        # A manifest with no dependencies yet, as `zig init` would leave it.
        project.write_zon({})
        return project

    def azazel(self, project: Project, *args: str) -> tuple[int, str]:
        result = project.azazel(*args)
        return result.returncode, result.stdout

    def run_app(self, project: Project) -> int:
        result = project.zig_build()
        self.assertEqual(result.returncode, 0, result.stdout)
        return project.run(str(project.root / "zig-out" / "bin" / "app")).returncode

    def test_zon_write_then_module_imports_the_dependency(self) -> None:
        project = self.project()
        code, out = self.azazel(project, "check")
        self.assertNotEqual(code, 0)
        self.assertIn("package 'maths' is declared in project.cue but missing from build.zig.zon", out)
        self.assertIn("run `azazel zon write`", out)

        code, out = self.azazel(project, "zon", "write")
        self.assertEqual(code, 0, out)
        manifest = (project.root / "build.zig.zon").read_text()
        self.assertEqual(zon.read_dependencies(manifest), [zon.Dependency(alias="maths", path="deps/maths")])
        self.assertIn(".name = .azazel_fixture,", manifest)

        self.assertEqual(self.azazel(project, "zon", "check")[0], 0)
        self.assertEqual(self.azazel(project, "check")[0], 0)
        self.assertEqual(self.run_app(project), 42)

    def test_lazy_package_is_imported(self) -> None:
        project = self.project(lazy=True)
        self.assertEqual(self.azazel(project, "zon", "write")[0], 0)
        self.assertIn(".lazy = true,", (project.root / "build.zig.zon").read_text())
        self.assertIn('.lazy = true }', (project.root / "build_spec.zig").read_text() if project.gen().returncode == 0 else "")
        self.assertEqual(self.run_app(project), 42)

    def test_check_reports_drift_and_undeclared_packages(self) -> None:
        project = self.project()
        project.write_zon({"maths": {"path": "deps/elsewhere"}, "stray": {"path": "deps/stray"}})
        code, out = self.azazel(project, "zon", "check")
        self.assertNotEqual(code, 0)
        self.assertIn("package 'maths' path differs: project.cue has 'deps/maths', build.zig.zon has 'deps/elsewhere'", out)
        self.assertIn("dependency 'stray' is in build.zig.zon but not declared in project.cue packages", out)

        undeclared = Project(
            '\napp: #Module & {\n\tkind: "exe"\n\troot: "src/main.zig"\n'
            '\tpkg_imports: [{alias: "m", package: "ghost", module: "x"}]\n}\n'
        )
        self.addCleanup(undeclared.close)
        code, out = self.azazel(undeclared, "check")
        self.assertNotEqual(code, 0)
        self.assertIn("module 'app' imports package 'ghost', which is not declared in packages", out)

    def test_zon_import_prints_packages_for_an_upstream_manifest(self) -> None:
        project = self.project()
        project.write("upstream.zon", CAPY_ZON)
        code, out = self.azazel(project, "zon", "import", "upstream.zon")
        self.assertEqual(code, 0, out)
        self.assertIn('"zig-objc": {', out)
        self.assertIn('hash: "12206038da3a8d42de25babfadaa3b8fb01c223850a1f1ce309034172d150df61a8c"', out)
        self.assertIn("lazy: true", out)


class LibvaxisSlicePackages(unittest.TestCase):
    def test_slice_packages_come_from_the_upstream_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp)
            (clone / "build.zig.zon").write_text(
                zon_text(
                    "vaxis",
                    {
                        "zigimg": {"url": "git+https://example.org/zigimg#abc", "hash": "zigimg-0.1.0-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
                        "uucode": {"url": "git+https://example.org/uucode#def", "hash": "uucode-0.2.0-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "lazy": True},
                        "unused": {"path": "x"},
                    },
                )
            )
            repo = huge_corpus.select_repos(["libvaxis"])[0]
            huge_corpus.write_executable_parity_workspace(clone, repo)
            workspace = clone / ".azazel" / "parity-work"
            project = (workspace / "project.cue").read_text()
            self.assertIn('url: "git+https://example.org/uucode#def"', project)
            self.assertIn("lazy: true", project)
            self.assertNotIn("unused", project)
            deps = zon.read_dependencies((workspace / "build.zig.zon").read_text())
            self.assertEqual([(dep.alias, dep.lazy) for dep in deps], [("zigimg", False), ("uucode", True)])
            self.assertEqual(deps[0].hash, "zigimg-0.1.0-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

    def test_missing_upstream_dependency_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "build.zig.zon").write_text(zon_text("vaxis", {"zigimg": {"path": "x"}}))
            with self.assertRaises(SystemExit) as ctx:
                huge_corpus.upstream_packages(Path(tmp), ("zigimg", "uucode"))
            self.assertIn("no dependency named uucode", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
