"""Tests for project-required Zig toolchain resolution.

Fake `zig` binaries are shell scripts that print a fixed version, so every
resolution path runs without a real toolchain or the network. The download
path is served from a local HTTP server.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import huge_corpus  # noqa: E402
import zig_toolchain  # noqa: E402
from zig_toolchain import ToolchainSpec, ZigVersion  # noqa: E402


ZLS = ToolchainSpec(
    id="0.17-dev",
    kind="dev-window",
    min_version="0.17.0-dev.292+fc1c83a36",
    max_version="0.17.0-dev.601+0ff175b69",
)
MACH = ToolchainSpec(
    id="mach-2026.4.10",
    kind="custom",
    distribution="mach",
    name="2026.4.10-mach",
    version="0.16.0-dev.3142+5ccfeb926",
)

FAKE_ZIG = '#!/bin/sh\nif [ "$1" = version ]; then echo "{version}"; exit 0; fi\nexit 1\n'


def fake_zig(directory: Path, version: str, name: str = "zig") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / name
    binary.write_text(FAKE_ZIG.format(version=version), encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return binary


def toolchain_tarball(version: str, platform_key: str = "aarch64-macos") -> bytes:
    """A tar.xz laid out like an official Zig release."""
    buffer = io.BytesIO()
    script = FAKE_ZIG.format(version=version).encode()
    with tarfile.open(fileobj=buffer, mode="w:xz") as bundle:
        info = tarfile.TarInfo(f"zig-{platform_key}-{version}/zig")
        info.size = len(script)
        info.mode = 0o755
        bundle.addfile(info, io.BytesIO(script))
    return buffer.getvalue()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


class VersionOrder(unittest.TestCase):
    def test_dev_builds_order_by_commit_count(self) -> None:
        self.assertLess(ZigVersion.parse("0.17.0-dev.292+fc1c83a36"), ZigVersion.parse("0.17.0-dev.601+0ff175b69"))
        self.assertLess(ZigVersion.parse("0.17.0-dev.601+0ff175b69"), ZigVersion.parse("0.17.0-dev.1509+bb296ab9b"))

    def test_release_follows_its_dev_builds(self) -> None:
        self.assertLess(ZigVersion.parse("0.17.0-dev.1509+bb296ab9b"), ZigVersion.parse("0.17.0"))
        self.assertLess(ZigVersion.parse("0.16.0"), ZigVersion.parse("0.17.0-dev.1"))

    def test_build_metadata_does_not_affect_order(self) -> None:
        self.assertEqual(ZigVersion.parse("0.17.0-dev.292+aaaa"), ZigVersion.parse("0.17.0-dev.292+bbbb"))

    def test_round_trip(self) -> None:
        for text in ("0.14.1", "0.17.0-dev.292+fc1c83a36"):
            self.assertEqual(str(ZigVersion.parse(text)), text)

    def test_rejects_non_versions(self) -> None:
        with self.assertRaises(zig_toolchain.VersionError):
            ZigVersion.parse("2026.4.10-mach build")


class Verdicts(unittest.TestCase):
    def test_exact(self) -> None:
        spec = ToolchainSpec.exact("0.14.1")
        self.assertEqual(spec.verdict("0.14.1"), "ok")
        self.assertEqual(spec.verdict("0.14.0"), "too-old")
        self.assertEqual(spec.verdict("0.15.2"), "too-new")

    def test_dev_window_bounds(self) -> None:
        self.assertEqual(ZLS.verdict("0.17.0-dev.291+aaaaaaaaa"), "too-old")
        self.assertEqual(ZLS.verdict("0.17.0-dev.292+fc1c83a36"), "ok")
        self.assertEqual(ZLS.verdict("0.17.0-dev.600+aaaaaaaaa"), "ok")
        self.assertEqual(ZLS.verdict("0.17.0-dev.601+0ff175b69"), "too-new")
        self.assertEqual(ZLS.verdict("0.17.0"), "too-new")

    def test_open_ended_window(self) -> None:
        spec = ToolchainSpec(id="min-0.14.1", kind="dev-window", min_version="0.14.1")
        self.assertEqual(spec.verdict("0.16.0"), "ok")
        self.assertEqual(spec.verdict("0.14.0"), "too-old")

    def test_custom_matches_reported_version(self) -> None:
        self.assertEqual(MACH.verdict("0.16.0-dev.3142+5ccfeb926"), "ok")
        self.assertEqual(MACH.verdict("0.16.0"), "too-new")

    def test_spec_validation(self) -> None:
        with self.assertRaises(ValueError):
            ToolchainSpec(id="x", kind="nightly", version="0.16.0")
        with self.assertRaises(ValueError):
            ToolchainSpec(id="x", kind="dev-window")
        with self.assertRaises(ValueError):
            ToolchainSpec(id="x", kind="custom", version="0.16.0")

    def test_env_key(self) -> None:
        self.assertEqual(ZLS.env_key, "AZAZEL_ZIG_017DEV")
        self.assertEqual(MACH.env_key, "AZAZEL_ZIG_MACH2026410")


class LocalResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "toolchains"
        self.cache.mkdir()
        self.env = {"PATH": str(self.root / "bin")}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def resolve(self, spec: ToolchainSpec, **kwargs: object) -> zig_toolchain.Resolution:
        return zig_toolchain.resolve(spec, env=self.env, roots=[self.cache], **kwargs)

    def test_missing_names_the_window(self) -> None:
        result = self.resolve(ZLS)
        self.assertEqual(result.status, "missing-toolchain")
        self.assertFalse(result.found)
        self.assertIn(">= 0.17.0-dev.292+fc1c83a36", result.diagnostic)
        self.assertIn("< 0.17.0-dev.601+0ff175b69", result.diagnostic)
        self.assertIn("AZAZEL_ZIG_017DEV", result.diagnostic)

    def test_too_new_dev_build_is_unsupported(self) -> None:
        binary = fake_zig(self.cache / "zig-aarch64-macos-0.17.0-dev.1509+bb296ab9b", "0.17.0-dev.1509+bb296ab9b")
        result = self.resolve(ZLS)
        self.assertEqual(result.status, "unsupported-toolchain")
        self.assertEqual(result.path, "")
        self.assertIn(f"{binary} is 0.17.0-dev.1509+bb296ab9b: too new", result.diagnostic)

    def test_too_old_dev_build_is_unsupported(self) -> None:
        fake_zig(self.cache / "old", "0.17.0-dev.100+aaaaaaaaa")
        result = self.resolve(ZLS)
        self.assertEqual(result.status, "unsupported-toolchain")
        self.assertIn("too old", result.diagnostic)

    def test_other_lane_does_not_count_as_unsupported(self) -> None:
        fake_zig(self.cache / "zig-0.14.0", "0.14.0")
        self.assertEqual(self.resolve(ZLS).status, "missing-toolchain")

    def test_window_picks_newest_accepted_build(self) -> None:
        fake_zig(self.cache / "a", "0.17.0-dev.300+aaaaaaaaa")
        newest = fake_zig(self.cache / "b", "0.17.0-dev.590+bbbbbbbbb")
        fake_zig(self.cache / "c", "0.17.0-dev.1509+bb296ab9b")
        result = self.resolve(ZLS)
        self.assertTrue(result.found)
        self.assertEqual(result.path, str(newest))
        self.assertEqual(result.version, "0.17.0-dev.590+bbbbbbbbb")

    def test_exact_patch_mismatch_is_unsupported(self) -> None:
        fake_zig(self.cache / "zig-0.14.0", "0.14.0")
        result = self.resolve(ToolchainSpec.exact("0.14.1"))
        self.assertEqual(result.status, "unsupported-toolchain")
        self.assertIn("Zig 0.14.1 exactly", result.diagnostic)

    def test_custom_distribution_found_in_cache(self) -> None:
        binary = fake_zig(self.cache / "zig-mach-2026.4.10", "0.16.0-dev.3142+5ccfeb926")
        result = self.resolve(MACH)
        self.assertTrue(result.found)
        self.assertEqual(result.path, str(binary))

    def test_configured_path_wins(self) -> None:
        fake_zig(self.cache / "cached", "0.17.0-dev.590+bbbbbbbbb")
        configured = fake_zig(self.root / "elsewhere", "0.17.0-dev.300+aaaaaaaaa")
        self.env["AZAZEL_ZIG_017DEV"] = str(configured)
        result = self.resolve(ZLS)
        self.assertEqual(result.path, str(configured))

    def test_configured_path_is_still_verified(self) -> None:
        configured = fake_zig(self.root / "elsewhere", "0.15.2")
        self.env["AZAZEL_ZIG_017DEV"] = str(configured)
        result = self.resolve(ZLS)
        self.assertEqual(result.status, "unsupported-toolchain")
        self.assertIn("0.15.2: too old", result.diagnostic)

    def test_configured_path_that_does_not_run(self) -> None:
        self.env["AZAZEL_ZIG_017DEV"] = str(self.root / "nope" / "zig")
        result = self.resolve(ZLS)
        self.assertEqual(result.status, "missing-toolchain")
        self.assertIn("could not be run", result.diagnostic)

    def test_versioned_binary_on_path(self) -> None:
        binary = fake_zig(self.root / "bin", "0.16.0", name="zig-0.16.0")
        result = self.resolve(ToolchainSpec.exact("0.16.0"))
        self.assertEqual(result.path, str(binary))

    def test_plain_zig_on_path_is_used_only_when_it_matches(self) -> None:
        binary = fake_zig(self.root / "bin", "0.16.0")
        self.assertEqual(self.resolve(ToolchainSpec.exact("0.16.0")).path, str(binary))
        self.assertFalse(self.resolve(ToolchainSpec.exact("0.15.2")).found)

    def test_offline_by_default(self) -> None:
        calls: list[str] = []
        original = zig_toolchain._read_url
        zig_toolchain._read_url = lambda url, timeout=60: calls.append(url) or b"{}"
        try:
            self.resolve(MACH)
        finally:
            zig_toolchain._read_url = original
        self.assertEqual(calls, [])


class FetchResolution(unittest.TestCase):
    PLATFORM = "aarch64-macos"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.site = self.root / "site"
        self.site.mkdir()
        self.cache = self.root / "toolchains"
        handler = functools.partial(QuietHandler, directory=str(self.site))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def publish(self, key: str, version: str, *, corrupt: bool = False, serve: bool = True) -> None:
        data = toolchain_tarball(version, self.PLATFORM)
        name = f"zig-{self.PLATFORM}-{version}.tar.xz"
        if serve:
            (self.site / name).write_bytes(data)
        index_path = self.site / "index.json"
        index = json.loads(index_path.read_text()) if index_path.exists() else {}
        index[key] = {
            "version": version,
            self.PLATFORM: {
                "tarball": f"{self.base}/{name}",
                "shasum": "0" * 64 if corrupt else hashlib.sha256(data).hexdigest(),
            },
        }
        index_path.write_text(json.dumps(index))

    def resolve(self, spec: ToolchainSpec) -> zig_toolchain.Resolution:
        return zig_toolchain.resolve(
            spec,
            env={"PATH": ""},
            roots=[self.cache],
            fetch=True,
            platform_key=self.PLATFORM,
        )

    def mach(self) -> ToolchainSpec:
        return ToolchainSpec(
            id="mach-2026.4.10",
            kind="custom",
            distribution="mach",
            name="2026.4.10-mach",
            version="0.16.0-dev.3142+5ccfeb926",
            index_url=f"{self.base}/index.json",
        )

    def test_custom_distribution_is_fetched_and_installed(self) -> None:
        self.publish("2026.4.10-mach", "0.16.0-dev.3142+5ccfeb926")
        result = self.resolve(self.mach())
        self.assertTrue(result.found, result.diagnostic)
        self.assertEqual(result.version, "0.16.0-dev.3142+5ccfeb926")
        self.assertTrue(Path(result.path).is_file())
        self.assertEqual(Path(result.path).parent.parent, self.cache)
        # The installed build is found again without the network.
        again = zig_toolchain.resolve(self.mach(), env={"PATH": ""}, roots=[self.cache])
        self.assertEqual(again.path, result.path)

    def test_mirror_failure_is_reported_distinctly(self) -> None:
        self.publish("2026.4.10-mach", "0.16.0-dev.3142+5ccfeb926", serve=False)
        result = self.resolve(self.mach())
        self.assertEqual(result.status, "toolchain-fetch-failed")
        self.assertIn("download failed", result.diagnostic)
        self.assertIn("404", result.diagnostic)

    def test_index_without_the_named_build(self) -> None:
        self.publish("2026.6.18-mach", "0.17.0-dev.892+54537285c")
        result = self.resolve(self.mach())
        self.assertEqual(result.status, "toolchain-fetch-failed")
        self.assertIn("index does not list 2026.4.10-mach", result.diagnostic)

    def test_checksum_mismatch_is_rejected(self) -> None:
        self.publish("2026.4.10-mach", "0.16.0-dev.3142+5ccfeb926", corrupt=True)
        result = self.resolve(self.mach())
        self.assertEqual(result.status, "toolchain-fetch-failed")
        self.assertIn("sha256 mismatch", result.diagnostic)
        self.assertEqual(list(self.cache.glob("zig-*")), [])

    def test_build_that_reports_another_version_is_rejected(self) -> None:
        self.publish("2026.4.10-mach", "0.16.0")
        result = self.resolve(self.mach())
        self.assertEqual(result.status, "toolchain-fetch-failed")
        self.assertIn("downloaded build reports 0.16.0", result.diagnostic)

    def test_window_with_no_published_build_lists_what_exists(self) -> None:
        self.publish("2026.6.18-mach", "0.17.0-dev.892+54537285c")
        self.publish("master", "0.18.0-dev.1186+9dd2c8c88")
        spec = ToolchainSpec(
            id="0.17-dev",
            kind="dev-window",
            min_version=ZLS.min_version,
            max_version=ZLS.max_version,
            index_url=f"{self.base}/index.json",
        )
        result = self.resolve(spec)
        self.assertEqual(result.status, "toolchain-fetch-failed")
        self.assertIn("0.17.0-dev.892+54537285c is too new", result.diagnostic)
        self.assertNotIn("0.18.0-dev", result.diagnostic)

    def test_window_fetches_newest_published_build_inside_it(self) -> None:
        self.publish("a", "0.17.0-dev.300+aaaaaaaaa")
        self.publish("b", "0.17.0-dev.590+bbbbbbbbb")
        self.publish("c", "0.17.0-dev.892+54537285c")
        spec = ToolchainSpec(
            id="0.17-dev",
            kind="dev-window",
            min_version=ZLS.min_version,
            max_version=ZLS.max_version,
            index_url=f"{self.base}/index.json",
        )
        result = self.resolve(spec)
        self.assertTrue(result.found, result.diagnostic)
        self.assertEqual(result.version, "0.17.0-dev.590+bbbbbbbbb")

    def test_exact_release_falls_back_to_a_known_mirror(self) -> None:
        # The index points at a tarball the origin no longer serves. A mirror
        # serves the same file name, and the index checksum still applies.
        self.publish("0.16.0", "0.16.0", serve=False)
        mirror = self.site / "mirror"
        mirror.mkdir()
        (mirror / f"zig-{self.PLATFORM}-0.16.0.tar.xz").write_bytes(toolchain_tarball("0.16.0", self.PLATFORM))
        saved = (zig_toolchain.OFFICIAL_INDEX, zig_toolchain.KNOWN_MIRRORS)
        zig_toolchain.OFFICIAL_INDEX = f"{self.base}/index.json"
        zig_toolchain.KNOWN_MIRRORS = (f"{self.base}/mirror",)
        try:
            result = self.resolve(ToolchainSpec.exact("0.16.0"))
        finally:
            zig_toolchain.OFFICIAL_INDEX, zig_toolchain.KNOWN_MIRRORS = saved
        self.assertTrue(result.found, result.diagnostic)
        self.assertIn("/mirror/", result.diagnostic)
        self.assertEqual(len(result.fetch_attempts), 1)
        self.assertIn("download failed", result.fetch_attempts[0]["error"])

    def test_unreachable_index(self) -> None:
        spec = ToolchainSpec(id="0.16.0", version="0.16.0", index_url="http://127.0.0.1:9/index.json")
        result = self.resolve(spec)
        self.assertEqual(result.status, "toolchain-fetch-failed")
        self.assertIn("index unavailable", result.diagnostic)


class CorpusManifests(unittest.TestCase):
    """The corpus runner reports toolchain failures from the manifest alone."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "toolchains"
        self.cache.mkdir()
        self.saved_env = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("AZAZEL_ZIG_"):
                del os.environ[key]
        os.environ["AZAZEL_TOOLCHAIN_ROOT"] = str(self.cache)
        os.environ["HOME"] = str(self.root / "home")
        os.environ["PATH"] = "/usr/bin:/bin"
        huge_corpus._RESOLUTIONS.clear()
        huge_corpus.FETCH_TOOLCHAINS = False
        self.clones: list[str] = []
        self.saved_clone = huge_corpus.ensure_clone
        huge_corpus.ensure_clone = lambda root, repo: self.clones.append(repo.name) or (root / repo.name)

    def tearDown(self) -> None:
        huge_corpus.ensure_clone = self.saved_clone
        os.environ.clear()
        os.environ.update(self.saved_env)
        huge_corpus._RESOLUTIONS.clear()
        self.tmp.cleanup()

    def build(self, name: str) -> dict[str, object]:
        out = self.root / "out"
        out.mkdir(exist_ok=True)
        huge_corpus.run_build(out, huge_corpus.select_repos([name]))
        return json.loads((out / "build-results.json").read_text())[0]

    def test_manifest_declares_toolchain_apart_from_lanes(self) -> None:
        zls = huge_corpus.select_repos(["zls"])[0].manifest()
        self.assertEqual(zls["preferred_zig"], "0.15")
        self.assertEqual(zls["toolchain"]["kind"], "dev-window")
        self.assertEqual(zls["toolchain"]["min_version"], "0.17.0-dev.292+fc1c83a36")
        self.assertEqual(zls["toolchain"]["max_version"], "0.17.0-dev.601+0ff175b69")
        mach = huge_corpus.select_repos(["mach"])[0].manifest()
        self.assertEqual(mach["toolchain"]["kind"], "custom")
        self.assertEqual(mach["toolchain"]["name"], "2026.4.10-mach")
        capy = huge_corpus.select_repos(["capy"])[0].manifest()
        self.assertEqual(capy["toolchain"], {**capy["toolchain"], "kind": "exact", "version": "0.14.1"})

    def test_every_repo_has_a_valid_toolchain(self) -> None:
        for repo in huge_corpus.REPOS:
            spec = repo.required_toolchain()
            self.assertEqual(spec.id, repo.build_zig)
            self.assertTrue(spec.requirement())

    def test_zls_build_reports_the_missing_window(self) -> None:
        entry = self.build("zls")
        self.assertEqual(entry["classification"], "missing-toolchain")
        self.assertTrue(entry["matches_expected"])
        self.assertIn(">= 0.17.0-dev.292+fc1c83a36 and < 0.17.0-dev.601+0ff175b69", entry["output"])
        self.assertEqual(entry["toolchain"]["kind"], "dev-window")
        self.assertEqual(self.clones, [])

    def test_zls_build_reports_a_too_new_dev_build(self) -> None:
        fake_zig(self.cache / "zig-aarch64-macos-0.17.0-dev.1509+bb296ab9b", "0.17.0-dev.1509+bb296ab9b")
        entry = self.build("zls")
        self.assertEqual(entry["classification"], "unsupported-toolchain")
        self.assertIn("0.17.0-dev.1509+bb296ab9b: too new", entry["output"])
        self.assertIn("replace the local build", entry["next_action"])

    def test_mach_build_uses_a_local_mach_zig(self) -> None:
        binary = fake_zig(self.cache / "zig-mach-2026.4.10", "0.16.0-dev.3142+5ccfeb926")
        (self.root / "out" / "mach").mkdir(parents=True)
        entry = self.build("mach")
        self.assertEqual(entry["toolchain"]["status"], "found")
        self.assertEqual(entry["command"][0], str(binary))
        self.assertEqual(self.clones, ["mach"])
        # The fake binary cannot build, so the result is a build failure and
        # the toolchain is no longer the reported cause.
        self.assertNotIn(entry["classification"], ("missing-toolchain", "unsupported-toolchain"))

    def test_mach_mirror_failure_is_distinct_from_missing(self) -> None:
        self.assertEqual(self.build("mach")["classification"], "missing-toolchain")
        huge_corpus._RESOLUTIONS.clear()
        huge_corpus.FETCH_TOOLCHAINS = True
        original = zig_toolchain._read_url

        def refuse(url: str, timeout: int = 60) -> bytes:
            raise OSError("unable to fetch: UpstreamError")

        zig_toolchain._read_url = refuse
        try:
            entry = self.build("mach")
        finally:
            zig_toolchain._read_url = original
        self.assertEqual(entry["classification"], "toolchain-fetch-failed")
        self.assertIn("pkg.machengine.org", entry["output"])
        self.assertIn("UpstreamError", entry["output"])

    def test_doctor_reports_the_diagnostic(self) -> None:
        entry = huge_corpus.doctor_entry(huge_corpus.select_repos(["zls"])[0])
        self.assertFalse(entry["ready"])
        self.assertEqual(entry["missing"], ["zig:0.17-dev"])
        self.assertEqual(entry["toolchain"]["status"], "missing-toolchain")
        self.assertIn("--fetch-toolchains", entry["next_action"])


if __name__ == "__main__":
    unittest.main()
