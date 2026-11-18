"""Project-required Zig toolchains for the corpus runner.

Azazel's own generator is maintained as stable API lanes ("0.14", "0.15",
"0.16"). A real project often needs something narrower: one exact release, a
window of development builds, or a custom distribution such as Mach's nominated
Zig. This module describes those requirements and resolves them.

Resolution order:

1. a configured path (`AZAZEL_ZIG_<ID>`)
2. the local cache (`AZAZEL_TOOLCHAIN_ROOT`, then `~/zig`)
3. binaries on `PATH`
4. a download from the official index or a known mirror, only when the caller
   asks for it

Every candidate is run with `zig version` and compared against the requirement,
so a binary that is too old or too new is reported as such and never used.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


OFFICIAL_INDEX = "https://ziglang.org/download/index.json"
MACH_INDEX = "https://pkg.machengine.org/zig/index.json"
# Mirrors that serve official tarballs under the same file name. The checksum
# always comes from the index, so a mirror cannot substitute a different build.
KNOWN_MIRRORS = (
    "https://pkg.machengine.org/zig",
    "https://zigmirror.hryx.net/zig",
)

KINDS = ("exact", "dev-window", "custom")

# Resolution statuses. Each one is also the build classification the corpus
# runner reports when the toolchain is the reason a build did not start.
FOUND = "found"
MISSING = "missing-toolchain"
UNSUPPORTED = "unsupported-toolchain"
FETCH_FAILED = "toolchain-fetch-failed"

_VERSION_RE = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
)


class VersionError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class ZigVersion:
    """A Zig version ordered the way `std.SemanticVersion.order` orders it."""

    major: int
    minor: int
    patch: int
    # A release sorts after every pre-release of the same major.minor.patch.
    release: bool
    pre: tuple[tuple[int, int | str], ...]
    build: str = field(default="", compare=False)

    @staticmethod
    def parse(text: str) -> "ZigVersion":
        match = _VERSION_RE.match(text.strip())
        if not match:
            raise VersionError(f"not a Zig version: {text!r}")
        major, minor, patch, pre, build = match.groups()
        parts: list[tuple[int, int | str]] = []
        for item in (pre or "").split("."):
            if not item:
                continue
            # Numeric identifiers sort before alphanumeric ones.
            parts.append((0, int(item)) if item.isdigit() else (1, item))
        return ZigVersion(int(major), int(minor), int(patch), pre is None, tuple(parts), build or "")

    @property
    def lane(self) -> str:
        return f"{self.major}.{self.minor}"

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            text += "-" + ".".join(str(value) for _, value in self.pre)
        if self.build:
            text += "+" + self.build
        return text


@dataclass(frozen=True)
class ToolchainSpec:
    """The Zig toolchain a project requires.

    `id` is the stable name used in manifests, cache directories and the
    `AZAZEL_ZIG_<ID>` override.

    exact       `version` is the only accepted `zig version` output.
    dev-window  accepts `min_version` (inclusive) up to `max_version`
                (exclusive). An empty bound is open.
    custom      a distribution with its own version names. `name` is the
                distribution's name for the build, and `version` is what its
                `zig version` prints.
    """

    id: str
    kind: str = "exact"
    version: str = ""
    min_version: str = ""
    max_version: str = ""
    distribution: str = "zig"
    name: str = ""
    index_url: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"toolchain {self.id!r}: unknown kind {self.kind!r}")
        if self.kind in ("exact", "custom") and not self.version:
            raise ValueError(f"toolchain {self.id!r}: {self.kind} toolchains need a version")
        if self.kind == "custom" and not self.name:
            raise ValueError(f"toolchain {self.id!r}: custom toolchains need a distribution name")
        if self.kind == "dev-window" and not (self.min_version or self.max_version):
            raise ValueError(f"toolchain {self.id!r}: a dev window needs at least one bound")
        for text in (self.version, self.min_version, self.max_version):
            if text:
                ZigVersion.parse(text)

    @staticmethod
    def exact(version: str, source: str = "") -> "ToolchainSpec":
        return ToolchainSpec(id=version, kind="exact", version=version, source=source)

    @property
    def env_key(self) -> str:
        return "AZAZEL_ZIG_" + "".join(ch for ch in self.id.upper() if ch.isalnum())

    @property
    def lane(self) -> str:
        return ZigVersion.parse(self.version or self.min_version or self.max_version).lane

    def requirement(self) -> str:
        if self.kind == "exact":
            return f"Zig {self.version} exactly"
        if self.kind == "custom":
            return f"{self.distribution} Zig {self.name} (reports {self.version})"
        bounds = []
        if self.min_version:
            bounds.append(f">= {self.min_version}")
        if self.max_version:
            bounds.append(f"< {self.max_version}")
        return "Zig " + " and ".join(bounds)

    def verdict(self, reported: str) -> str:
        """Compare a `zig version` string with the requirement.

        Returns "ok", "too-old", "too-new", or "unparsed".
        """
        try:
            found = ZigVersion.parse(reported)
        except VersionError:
            return "unparsed"
        if self.kind in ("exact", "custom"):
            wanted = ZigVersion.parse(self.version)
            if found == wanted:
                return "ok"
            return "too-old" if found < wanted else "too-new"
        if self.min_version and found < ZigVersion.parse(self.min_version):
            return "too-old"
        if self.max_version and found >= ZigVersion.parse(self.max_version):
            return "too-new"
        return "ok"

    def manifest(self) -> dict[str, object]:
        data: dict[str, object] = {"id": self.id, "kind": self.kind, "requirement": self.requirement()}
        for key in ("version", "min_version", "max_version", "name", "index_url", "source"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.distribution != "zig":
            data["distribution"] = self.distribution
        data["env_override"] = self.env_key
        return data


@dataclass
class Candidate:
    path: str
    origin: str
    version: str = ""
    verdict: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "origin": self.origin, "version": self.version, "verdict": self.verdict}


@dataclass
class Resolution:
    spec: ToolchainSpec
    status: str
    path: str = ""
    version: str = ""
    diagnostic: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    fetch_attempts: list[dict[str, str]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.status == FOUND

    def as_dict(self) -> dict[str, object]:
        return {
            **self.spec.manifest(),
            "status": self.status,
            "found": self.found,
            "path": self.path,
            "resolved_version": self.version,
            "diagnostic": self.diagnostic,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "fetch_attempts": list(self.fetch_attempts),
        }


def toolchain_root() -> Path:
    default = Path(__file__).resolve().parents[2] / ".toolchains"
    return Path(os.environ.get("AZAZEL_TOOLCHAIN_ROOT", default))


def host_platform() -> str:
    """The `<arch>-<os>` name Zig download indexes use for this machine."""
    machine = platform.machine().lower()
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine)
    system = platform.system().lower()
    os_name = {"darwin": "macos"}.get(system, system)
    return f"{arch}-{os_name}"


def zig_version_of(path: str) -> str:
    """Run `<path> version`. Returns "" when the binary cannot be run."""
    try:
        result = subprocess.run(
            [path, "version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _local_candidates(spec: ToolchainSpec, env: dict[str, str], roots: list[Path]) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    def add(path: Path | str, origin: str) -> None:
        text = str(path)
        if text in seen:
            return
        seen.add(text)
        candidates.append(Candidate(text, origin))

    configured = env.get(spec.env_key)
    if configured:
        add(configured, f"configured:{spec.env_key}")

    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            binary = child / "zig"
            if binary.is_file():
                add(binary, f"cache:{root}")

    search_path = env.get("PATH", "")
    names = [f"zig-{spec.id}"]
    if spec.version:
        names.append(f"zig-{spec.version}")
    if spec.name:
        names.append(f"zig-{spec.name}")
    names.append("zig")
    for name in names:
        found = shutil.which(name, path=search_path)
        if found:
            add(found, "path")
    return candidates


def _is_near_miss(spec: ToolchainSpec, candidate: Candidate) -> bool:
    """Whether a rejected binary is evidence of a wrong toolchain.

    An unrelated Zig on `PATH` does not make a requirement "unsupported". A
    binary configured for this requirement, or one from the same release lane,
    does.
    """
    if candidate.verdict not in ("too-old", "too-new"):
        return False
    if candidate.origin.startswith("configured:"):
        return True
    try:
        return ZigVersion.parse(candidate.version).lane == spec.lane
    except VersionError:
        return False


def _describe(candidate: Candidate) -> str:
    reason = {
        "too-old": "too old",
        "too-new": "too new",
        "not-runnable": "could not be run",
        "unparsed": "printed an unreadable version",
    }.get(candidate.verdict, candidate.verdict)
    version = candidate.version or "unknown version"
    return f"{candidate.path} is {version}: {reason}"


def resolve(
    spec: ToolchainSpec,
    *,
    env: dict[str, str] | None = None,
    roots: list[Path] | None = None,
    fetch: bool = False,
    install_root: Path | None = None,
    platform_key: str | None = None,
) -> Resolution:
    """Find a Zig binary that satisfies `spec`.

    Without `fetch` this never touches the network.
    """
    env = dict(os.environ if env is None else env)
    if roots is None:
        roots = [toolchain_root(), Path.home() / "zig"]

    candidates = _local_candidates(spec, env, roots)
    accepted: list[tuple[ZigVersion, Candidate]] = []
    for candidate in candidates:
        candidate.version = zig_version_of(candidate.path)
        if not candidate.version:
            candidate.verdict = "not-runnable"
            continue
        candidate.verdict = spec.verdict(candidate.version)
        if candidate.verdict == "ok":
            accepted.append((ZigVersion.parse(candidate.version), candidate))

    if accepted:
        # A configured path wins. Otherwise take the newest accepted build.
        configured = [item for item in accepted if item[1].origin.startswith("configured:")]
        _, best = configured[0] if configured else max(accepted, key=lambda item: item[0])
        return Resolution(
            spec,
            FOUND,
            path=best.path,
            version=best.version,
            diagnostic=f"{spec.requirement()}: using {best.path} ({best.version})",
            candidates=candidates,
        )

    near = [candidate for candidate in candidates if _is_near_miss(spec, candidate)]
    broken = [
        candidate
        for candidate in candidates
        if candidate.origin.startswith("configured:") and candidate.verdict in ("not-runnable", "unparsed")
    ]
    resolution = Resolution(spec, UNSUPPORTED if near else MISSING, candidates=candidates)

    if fetch:
        fetched = _fetch(spec, resolution, install_root or roots[0], platform_key or host_platform())
        if fetched is not None:
            return fetched

    lines = [f"requires {spec.requirement()}"]
    if spec.source:
        lines[0] += f" ({spec.source})"
    for candidate in near + broken:
        lines.append(_describe(candidate))
    if not near and not broken:
        lines.append("no local Zig binary satisfies it")
    for attempt in resolution.fetch_attempts:
        lines.append(f"fetch {attempt['url']}: {attempt['error']}")
    if resolution.status != FETCH_FAILED:
        hint = f"set {spec.env_key} to a matching zig binary"
        if not fetch:
            hint += ", or rerun with --fetch-toolchains"
        lines.append(hint)
    resolution.diagnostic = "; ".join(lines)
    return resolution


# --- downloads ---------------------------------------------------------------


def _read_url(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "azazel-corpus"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _index_entries(spec: ToolchainSpec) -> list[str]:
    if spec.index_url:
        return [spec.index_url]
    if spec.kind == "dev-window":
        # The official index only lists the current master. Mach's index keeps
        # older nominated development builds.
        return [OFFICIAL_INDEX, MACH_INDEX]
    return [OFFICIAL_INDEX]


def _pick_release(spec: ToolchainSpec, index: dict[str, object], platform_key: str) -> tuple[dict[str, str] | None, str]:
    """Choose an index entry for `spec`. Returns (download, reason-if-none)."""
    rejected: list[str] = []
    best: tuple[ZigVersion, dict[str, str]] | None = None
    for key, entry in index.items():
        if not isinstance(entry, dict):
            continue
        version = str(entry.get("version", key))
        if spec.kind == "custom":
            if key != spec.name:
                continue
        elif spec.verdict(version) != "ok":
            verdict = spec.verdict(version)
            try:
                same_lane = ZigVersion.parse(version).lane == spec.lane
            except VersionError:
                same_lane = False
            if same_lane and verdict in ("too-old", "too-new"):
                rejected.append(f"{version} is {verdict.replace('-', ' ')}")
            continue
        download = entry.get(platform_key)
        if not isinstance(download, dict) or "tarball" not in download:
            return None, f"{key} has no build for {platform_key}"
        try:
            parsed = ZigVersion.parse(version)
        except VersionError:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, {"version": version, **{k: str(v) for k, v in download.items()}})
    if best is not None:
        return best[1], ""
    if spec.kind == "custom":
        return None, f"index does not list {spec.name}"
    if rejected:
        return None, "no published build satisfies the requirement: " + ", ".join(sorted(rejected))
    return None, "index lists no build that satisfies the requirement"


def _download_urls(spec: ToolchainSpec, download: dict[str, str]) -> list[str]:
    urls = [download["tarball"]]
    if download.get("zigTarball"):
        urls.append(download["zigTarball"])
    if spec.kind == "exact" and not spec.index_url:
        name = download["tarball"].rsplit("/", 1)[-1]
        urls.extend(f"{mirror}/{name}" for mirror in KNOWN_MIRRORS)
    return urls


def _extract(archive: Path, dest: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(dest)
        return
    with tarfile.open(archive) as bundle:
        if hasattr(tarfile, "data_filter"):
            bundle.extractall(dest, filter="data")
        else:
            bundle.extractall(dest)


def _fetch(spec: ToolchainSpec, resolution: Resolution, install_root: Path, platform_key: str) -> Resolution | None:
    """Download and install a build for `spec`.

    Returns a found Resolution on success. On failure it records each attempt
    on `resolution`, marks it FETCH_FAILED and returns None.
    """
    attempts = resolution.fetch_attempts
    download: dict[str, str] | None = None
    for index_url in _index_entries(spec):
        try:
            index = json.loads(_read_url(index_url))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            attempts.append({"url": index_url, "error": f"index unavailable: {exc}"})
            continue
        download, reason = _pick_release(spec, index, platform_key)
        if download is not None:
            break
        attempts.append({"url": index_url, "error": reason})

    if download is None:
        resolution.status = FETCH_FAILED
        return None

    install_root.mkdir(parents=True, exist_ok=True)
    for url in _download_urls(spec, download):
        name = url.rsplit("/", 1)[-1]
        with tempfile.TemporaryDirectory(dir=install_root, prefix=".fetch-") as scratch:
            archive = Path(scratch) / name
            try:
                archive.write_bytes(_read_url(url, timeout=600))
            except (OSError, urllib.error.URLError) as exc:
                attempts.append({"url": url, "error": f"download failed: {exc}"})
                continue
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            expected = download.get("shasum", "")
            if expected and digest != expected:
                attempts.append({"url": url, "error": f"sha256 mismatch: expected {expected}, got {digest}"})
                continue
            unpacked = Path(scratch) / "unpacked"
            try:
                _extract(archive, unpacked)
            except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
                attempts.append({"url": url, "error": f"archive could not be unpacked: {exc}"})
                continue
            binaries = sorted(unpacked.glob("*/zig")) or sorted(unpacked.glob("zig"))
            if not binaries:
                attempts.append({"url": url, "error": "archive holds no zig binary"})
                continue
            source_dir = binaries[0].parent
            target = install_root / f"zig-{platform_key}-{download['version']}"
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(source_dir), str(target))
            binary = target / "zig"
            reported = zig_version_of(str(binary))
            verdict = spec.verdict(reported) if reported else "not-runnable"
            if verdict != "ok":
                attempts.append({"url": url, "error": f"downloaded build reports {reported or 'nothing'}: {verdict}"})
                continue
            candidate = Candidate(str(binary), f"fetched:{url}", reported, "ok")
            return Resolution(
                spec,
                FOUND,
                path=str(binary),
                version=reported,
                diagnostic=f"{spec.requirement()}: fetched {url} into {target}",
                candidates=resolution.candidates + [candidate],
                fetch_attempts=attempts,
            )

    resolution.status = FETCH_FAILED
    return None
