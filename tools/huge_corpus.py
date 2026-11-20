#!/usr/bin/env python3
"""Prepare and audit the huge Zig project corpus.

The runner keeps the corpus reproducible:

* clone or update the godofecht forks
* create an `azazel-zaza-integration` branch
* add a `.azazel/` overlay describing the first integration target
* optionally run baseline `zig build --help`
* emit baseline-vs-Azazel parity readiness reports
* run executable Azazel target-slice parity proofs when a slice is modeled

It does not try to translate every upstream build graph in one pass. The overlay
is a stable landing zone that lets Azazel and Zaza grow against real projects.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import corpus_deps
import corpus_slices
import workspace
import zig_toolchain
import zon
from zig_toolchain import ToolchainSpec


BRANCH = "azazel-zaza-integration"
OUTPUT_TAIL_BYTES = 12000


SYSTEM_KINDS = ("tool", "pkg_config", "library", "framework", "header", "include_dir")


@dataclass(frozen=True)
class SystemRequirement:
    """One thing the host must provide, in the shape of `#SystemDep` in schema.cue."""

    name: str
    kind: str
    os: tuple[str, ...] = ()
    min_version: str = ""
    hint: str = ""

    def __post_init__(self) -> None:
        if self.kind not in SYSTEM_KINDS:
            raise ValueError(f"system requirement {self.name!r}: unknown kind {self.kind!r}")

    def manifest(self) -> dict[str, object]:
        data: dict[str, object] = {"name": self.name, "kind": self.kind, "os": list(self.os)}
        if self.min_version:
            data["min_version"] = self.min_version
        if self.hint:
            data["hint"] = self.hint
        return data

    def cue(self) -> str:
        fields = [f"name: {json.dumps(self.name)}", f"kind: {json.dumps(self.kind)}"]
        if self.os:
            fields.append("os: [" + ", ".join(json.dumps(item) for item in self.os) + "]")
        if self.min_version:
            fields.append(f"min_version: {json.dumps(self.min_version)}")
        if self.hint:
            fields.append(f"hint: {json.dumps(self.hint)}")
        return "{" + ", ".join(fields) + "}"


def tool(name: str, hint: str = "", os: tuple[str, ...] = ()) -> SystemRequirement:
    return SystemRequirement(name, "tool", os, hint=hint)


def pkg(name: str, hint: str = "", os: tuple[str, ...] = (), min_version: str = "") -> SystemRequirement:
    return SystemRequirement(name, "pkg_config", os, min_version, hint)


@dataclass(frozen=True)
class Repo:
    name: str
    upstream: str
    fork: str
    notes: str
    preferred_zig: str
    baseline_command: tuple[str, ...]
    build_zig: str
    build_command: tuple[str, ...]
    expected_build_classification: str
    azazel_command: tuple[str, ...]
    expected_classification: str
    first_targets: tuple[str, ...]
    system_deps: tuple[str, ...] = ()
    replacement_gaps: tuple[str, ...] = ()
    # Typed host requirements. The overlay project.cue receives the same list
    # as `system_deps`, so the corpus and an Azazel project share one shape.
    requirements: tuple[SystemRequirement, ...] = ()
    integration_kind: str = "azazel"
    parity_status: str = "scaffold-only"
    executable_parity_status: str = "not-modeled"
    executable_parity_command: tuple[str, ...] = ()
    expected_executable_parity_classification: str = "not-modeled"
    executable_parity_targets: tuple[str, ...] = ()
    executable_parity_install_checks: tuple[str, ...] = ()
    # Files the slice declares under `generated` with an install path. Each
    # must exist and be non-empty after the slice builds.
    executable_parity_generated_outputs: tuple[str, ...] = ()
    # The toolchain the project itself requires. When unset, `build_zig` is
    # read as one exact release. This is separate from the Azazel generator
    # lanes written into the overlay project.cue.
    toolchain: ToolchainSpec | None = None
    # Nested packages or sample directories a build can be limited to. A repo
    # that declares slices is built slice by slice, so a run does not compile
    # every sample. `--whole-repo` runs `build_command` instead.
    target_slices: tuple[workspace.TargetSlice, ...] = ()

    @property
    def required_tools(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.requirements if item.kind == "tool")

    @property
    def pkg_config_libs(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.requirements if item.kind == "pkg_config")

    def required_toolchain(self) -> ToolchainSpec:
        return self.toolchain or ToolchainSpec.exact(self.build_zig)

    def manifest(self) -> dict[str, object]:
        return {
            "name": self.name,
            "upstream": self.upstream,
            "fork": self.fork,
            "branch": BRANCH,
            "notes": self.notes,
            "status": "integration scaffold",
            "preferred_zig": self.preferred_zig,
            "baseline_command": list(self.baseline_command),
            "build_zig": self.build_zig,
            "toolchain": self.required_toolchain().manifest(),
            "build_command": list(self.build_command),
            "expected_build_classification": self.expected_build_classification,
            "azazel_command": list(self.azazel_command),
            "expected_baseline_classification": self.expected_classification,
            "first_targets": list(self.first_targets),
            "system_deps": list(self.system_deps),
            "required_tools": list(self.required_tools),
            "pkg_config_libs": list(self.pkg_config_libs),
            "requirements": [item.manifest() for item in self.requirements],
            "replacement_gaps": list(self.replacement_gaps),
            "integration_kind": self.integration_kind,
            "parity_status": self.parity_status,
            "executable_parity_status": self.executable_parity_status,
            "executable_parity_command": list(self.executable_parity_command),
            "expected_executable_parity_classification": self.expected_executable_parity_classification,
            "executable_parity_targets": list(self.executable_parity_targets),
            "executable_parity_install_checks": list(self.executable_parity_install_checks),
            "executable_parity_generated_outputs": list(self.executable_parity_generated_outputs),
            "target_slices": [item.manifest() for item in self.target_slices],
        }


REPOS = [
    Repo(
        "zls",
        "zigtools/zls",
        "godofecht/zls",
        "language server; generated version data, tests, release steps",
        "0.15",
        ("zig", "build", "--help"),
        "0.17-dev",
        ("zig", "build", "--summary", "all"),
        "missing-toolchain",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("exe:zls", "tests", "generated version data"),
        replacement_gaps=("exact dev-toolchain window", "package dependencies", "generated version data"),
        toolchain=ToolchainSpec(
            id="0.17-dev",
            kind="dev-window",
            min_version="0.17.0-dev.292+fc1c83a36",
            max_version="0.17.0-dev.601+0ff175b69",
            source="build.zig.zon minimum_zig_version and the build.zig upper bound (ZLS issue 3208)",
        ),
    ),
    Repo(
        "libxev",
        "mitchellh/libxev",
        "godofecht/libxev",
        "library variants, examples, benches, manpage generation",
        "0.16",
        ("zig", "build", "--help"),
        "0.16.0",
        ("zig", "build", "--summary", "all"),
        "ok",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-api-drift",
        ("lib:xev", "examples", "benchmarks", "manpage generation"),
        replacement_gaps=("library variants", "generated pkg-config/manpage outputs", "test artifact checks"),
        requirements=(
            SystemRequirement("ws2_32", "library", ("windows",)),
            SystemRequirement("mswsock", "library", ("windows",)),
        ),
        executable_parity_status="ready",
        executable_parity_command=("zig", "build", "--summary", "all"),
        expected_executable_parity_classification="ok",
        executable_parity_targets=("module:xev", "exe:xev_probe"),
    ),
    Repo(
        "river",
        "riverwm/river",
        "godofecht/river",
        "Wayland compositor; pkg-config, C sources, generated modules",
        "0.16",
        ("zig", "build", "--help"),
        "0.16.0",
        ("zig", "build", "--summary", "all"),
        "system-dependency",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("exe:river", "generated protocol modules", "C/system link metadata"),
        ("pkg-config", "wayland", "wlroots", "libevdev", "xkbcommon", "pixman"),
        ("system dependency preflight", "generated protocol modules", "pkg-config link metadata"),
        requirements=(
            tool("pkg-config"),
            tool("wayland-scanner", "part of the wayland development package"),
            pkg("wayland-scanner"),
            pkg("wayland-protocols"),
            pkg("wayland-server"),
            pkg("wlroots-0.20"),
            pkg("xkbcommon"),
            pkg("pixman-1"),
            pkg("libevdev"),
            pkg("libinput"),
        ),
    ),
    Repo(
        "mach",
        "hexops/mach",
        "godofecht/mach",
        "game engine; generated bindings, assets, custom Zig lane",
        "0.16",
        ("zig", "build", "--help"),
        "mach-2026.4.10",
        ("zig", "build", "--summary", "all"),
        "missing-toolchain",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("module:mach", "examples", "generated Vulkan bindings", "asset steps"),
        replacement_gaps=("custom Zig toolchain resolver", "generated Vulkan bindings", "asset pipeline"),
        toolchain=ToolchainSpec(
            id="mach-2026.4.10",
            kind="custom",
            distribution="mach",
            name="2026.4.10-mach",
            version="0.16.0-dev.3142+5ccfeb926",
            index_url=zig_toolchain.MACH_INDEX,
            source="build.zig.zon mach_zig_version",
        ),
    ),
    Repo(
        "microzig",
        "ZigEmbeddedGroup/microzig",
        "godofecht/microzig",
        "embedded workspace with many nested packages",
        "0.16",
        ("zig", "build", "--help"),
        "0.16.0",
        ("zig", "build", "--summary", "all"),
        "dependency-fetch",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("workspace packages", "board ports", "nested build packages", "tools"),
        replacement_gaps=("nested workspaces", "dependency archive handling", "embedded target slices"),
        target_slices=(
            workspace.TargetSlice(
                "ports",
                ("port/*/*",),
                mode="package",
                description="each chip port is a nested build package under port/<vendor>/<chip>",
                expected_classification="unverified",
            ),
            workspace.TargetSlice(
                "example-boards",
                ("examples/*/*",),
                mode="package",
                description="each vendor example directory is a nested build package",
                expected_classification="unverified",
            ),
        ),
    ),
    Repo(
        "libvaxis",
        "rockorager/libvaxis",
        "godofecht/libvaxis",
        "TUI library; example matrix and installable demos",
        "0.16",
        ("zig", "build", "--help"),
        "0.16.0",
        ("zig", "build", "--summary", "all"),
        "ok",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-api-drift",
        ("lib:vaxis", "example matrix", "installable demos", "tests"),
        replacement_gaps=("example matrix target selection", "installable demos", "test steps"),
        executable_parity_status="ready",
        executable_parity_command=("zig", "build", "--prefix", ".azazel-install", "--summary", "all"),
        expected_executable_parity_classification="ok",
        executable_parity_targets=(
            "module:vaxis",
            "exe:vaxis_probe",
            "package:zigimg",
            "package:uucode",
            "package-option:uucode:fields",
            "generated:unicode_tables:tables.zig",
        ),
        executable_parity_generated_outputs=(
            ".azazel-install/share/vaxis/unicode_tables.zig",
        ),
    ),
    Repo(
        "capy",
        "capy-ui/capy",
        "godofecht/capy",
        "native UI toolkit; exact Zig lane requirement",
        "0.14.1",
        ("zig", "build", "--help"),
        "0.14.1",
        ("zig", "build", "--summary", "all"),
        "dependency-format",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("lib:capy", "platform UI backend selection", "examples"),
        replacement_gaps=("transitive package format diagnostics", "platform UI backend metadata"),
    ),
    Repo(
        "zig-gamedev",
        "zig-gamedev/zig-gamedev",
        "godofecht/zig-gamedev",
        "large game-dev monorepo with assets and package deps",
        "0.15",
        ("zig", "build", "--help"),
        "0.15.2",
        ("zig", "build", "--summary", "all"),
        "ok",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-api-drift",
        ("package modules", "asset-heavy examples", "optional dependency selection"),
        replacement_gaps=("C/C++ dependency graph slices", "asset-heavy example selection", "framework/link metadata"),
        executable_parity_status="ready",
        executable_parity_command=("zig", "build", "--prefix", ".azazel-install", "--summary", "all"),
        expected_executable_parity_classification="ok",
        executable_parity_targets=(
            "module:zig_gamedev_vectormath",
            "exe:zig_gamedev_vectormath_probe",
            "package:zmath",
            "package:zopengl",
            "package:zglfw",
            "artifact:zglfw:glfw",
            "package:zmesh",
            "artifact:zmesh:zmesh",
            "package:znoise",
            "artifact:znoise:FastNoiseLite",
            "package:zgui",
            "artifact:zgui:imgui",
            "package-option:zgui:backend=glfw_wgpu",
            "package-option:zgui:with_implot=true",
            "package-option:zgpu:buffer_pool_size=256",
            "package:zgpu",
            "artifact:zgpu:zdawn",
            "package-library-path:dawn_aarch64_macos",
            "asset:sdl2_demo_content",
        ),
        executable_parity_install_checks=(
            ".azazel-install/bin/sdl2_demo_content/zero.png",
        ),
        target_slices=(
            workspace.TargetSlice(
                "minimal-samples",
                ("samples/minimal_*",),
                mode="steps",
                outputs=("bin/{name}",),
                description="the minimal samples, each built through its own step",
            ),
        ),
    ),
    Repo(
        "tigerbeetle",
        "tigerbeetle/tigerbeetle",
        "godofecht/tigerbeetle",
        "distributed financial database; large test/release matrix and generated tooling",
        "0.14.1",
        ("zig", "build", "--help"),
        "0.14.1",
        ("zig", "build", "--summary", "all"),
        "ok",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("exe:tigerbeetle", "tests", "simulator", "release/package steps"),
        requirements=(tool("git"),),
        replacement_gaps=(
            "large test matrix",
            "release/package artifact graph",
            "generated tooling",
            "target-specific optimization/link settings",
        ),
    ),
    Repo(
        "ghostty",
        "ghostty-org/ghostty",
        "godofecht/ghostty",
        "terminal app; native dependencies, resources, packaging, and platform targets",
        "0.16",
        ("zig", "build", "--help"),
        "0.16.0",
        ("zig", "build", "--summary", "all"),
        "platform-package",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("exe:ghostty", "native/system deps", "resources", "macOS app bundle/package steps"),
        requirements=(tool("pkg-config"),),
        replacement_gaps=(
            "native dependency preflight",
            "resource and app-bundle staging",
            "platform package/sign steps",
            "generated config/resources",
        ),
    ),
]


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if check and result.returncode != 0:
        raise SystemExit(
            f"command failed ({result.returncode}) in {cwd or Path.cwd()}:\n"
            f"{' '.join(cmd)}\n{result.stdout}"
        )
    return result


def repo_dir(root: Path, repo: Repo) -> Path:
    return root / repo.name


# Set by --slice, --target-path and --whole-repo.
REQUESTED_SLICES: tuple[str, ...] = ()
NARROW_PATHS: tuple[str, ...] = ()
WHOLE_REPO = False


def active_slices(repo: Repo) -> tuple[workspace.TargetSlice, ...]:
    """The slices a run builds for a repo.

    With no `--slice`, every declared slice. With `--slice NAME`, the named
    ones. `--whole-repo` selects none, so `build_command` runs as before.
    """
    if WHOLE_REPO:
        return ()
    if not REQUESTED_SLICES:
        return repo.target_slices
    return tuple(item for item in repo.target_slices if item.name in REQUESTED_SLICES)


def slice_selections(
    repo: Repo, path: Path, known_steps: set[str] | None = None
) -> list[workspace.SliceSelection]:
    selections = [
        workspace.resolve_slice(path, item, NARROW_PATHS, known_steps)
        for item in active_slices(repo)
    ]
    # `--target-path` narrows every slice. A slice it leaves empty is not part
    # of the run, unless it leaves all of them empty.
    if NARROW_PATHS:
        reached = [selection for selection in selections if selection.targets]
        if reached:
            return reached
    return selections


def selected_paths(selections: list[workspace.SliceSelection]) -> list[str]:
    return [target.path for selection in selections for target in selection.selected]


# Set by --fetch-toolchains. Resolution stays offline unless it is on.
FETCH_TOOLCHAINS = False
_RESOLUTIONS: dict[str, zig_toolchain.Resolution] = {}


def resolve_toolchain(repo: Repo) -> zig_toolchain.Resolution:
    """Resolve the Zig toolchain a repo requires, once per run."""
    spec = repo.required_toolchain()
    if spec.id not in _RESOLUTIONS:
        _RESOLUTIONS[spec.id] = zig_toolchain.resolve(spec, fetch=FETCH_TOOLCHAINS)
    return _RESOLUTIONS[spec.id]


def cue_preferred_lane(repo: Repo) -> str:
    if repo.preferred_zig.startswith("0.14"):
        return "0.14"
    if repo.preferred_zig.startswith("0.15"):
        return "0.15"
    if repo.preferred_zig.startswith("0.16"):
        return "0.16"
    return "0.15"


def ensure_clone(root: Path, repo: Repo) -> Path:
    path = repo_dir(root, repo)
    if path.exists():
        run(["git", "fetch", "origin"], cwd=path)
    else:
        run(["git", "clone", "--depth", "1", "--filter=blob:none", f"https://github.com/{repo.fork}.git", str(path)])
        run(["git", "remote", "add", "upstream", f"https://github.com/{repo.upstream}.git"], cwd=path)
    return path


def checkout_branch(path: Path) -> None:
    current = run(["git", "branch", "--show-current"], cwd=path).stdout.strip()
    existing = run(["git", "branch", "--list", BRANCH], cwd=path).stdout.strip()
    remote = run(["git", "fetch", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}"], cwd=path, check=False)
    if current != BRANCH:
        if existing:
            run(["git", "checkout", BRANCH], cwd=path)
        elif remote.returncode == 0:
            run(["git", "checkout", "-b", BRANCH, f"origin/{BRANCH}"], cwd=path)
        else:
            run(["git", "checkout", "-b", BRANCH], cwd=path)
    if remote.returncode == 0:
        run(["git", "merge", "--ff-only", f"origin/{BRANCH}"], cwd=path)


def origin_default_branch(path: Path) -> str:
    run(["git", "fetch", "origin"], cwd=path)
    ref = run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=path, check=False).stdout.strip()
    if ref.startswith("origin/"):
        return ref.removeprefix("origin/")
    set_head = run(["git", "remote", "set-head", "origin", "-a"], cwd=path, check=False)
    if set_head.returncode == 0:
        ref = run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=path, check=False).stdout.strip()
        if ref.startswith("origin/"):
            return ref.removeprefix("origin/")
    for candidate in ("main", "master", "trunk"):
        probe = run(["git", "rev-parse", "--verify", f"origin/{candidate}"], cwd=path, check=False)
        if probe.returncode == 0:
            return candidate
    raise SystemExit(f"could not resolve origin default branch in {path}")


def refresh_branch_base(path: Path) -> None:
    default_branch = origin_default_branch(path)
    run(["git", "checkout", "-B", BRANCH, f"origin/{default_branch}"], cwd=path)


def write_overlay(path: Path, repo: Repo) -> None:
    overlay = path / ".azazel"
    overlay.mkdir(exist_ok=True)
    manifest = repo.manifest()
    # Parsed from the repo's own build.zig.zon and build.zig, so the manifest
    # explains each dependency without a reader opening the upstream scripts.
    dependencies = corpus_deps.describe(path)
    manifest["dependencies"] = dependencies
    # Where each declared slice lands in this clone: the directories it
    # selects and their package-local roots.
    manifest["target_slice_selection"] = [
        workspace.resolve_slice(path, item).manifest() for item in repo.target_slices
    ]
    (overlay / "corpus.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (overlay / "dependencies.json").write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8")
    (overlay / "parity.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "repo": repo.name,
                "baseline": {
                    "command": list(repo.baseline_command),
                    "expected_classification": repo.expected_classification,
                    "preferred_zig": repo.preferred_zig,
                },
                "build": {
                    "command": list(repo.build_command),
                    "zig": repo.build_zig,
                    "toolchain": repo.required_toolchain().manifest(),
                    "expected_classification": repo.expected_build_classification,
                },
                "azazel": {
                    "command": list(repo.azazel_command),
                    "status": repo.parity_status,
                    "first_targets": list(repo.first_targets),
                    "system_deps": list(repo.system_deps),
                    "required_tools": list(repo.required_tools),
                    "pkg_config_libs": list(repo.pkg_config_libs),
                    "requirements": [item.manifest() for item in repo.requirements],
                    "replacement_gaps": list(repo.replacement_gaps),
                    "integration_kind": repo.integration_kind,
                    "executable_parity": {
                        "status": repo.executable_parity_status,
                        "command": list(repo.executable_parity_command),
                        "expected_classification": repo.expected_executable_parity_classification,
                        "targets": list(repo.executable_parity_targets),
                        "install_checks": list(repo.executable_parity_install_checks),
                        "generated_outputs": list(repo.executable_parity_generated_outputs),
                        "workdir": ".azazel/parity-work",
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (overlay / "README.md").write_text(
        f"""# Azazel/Zaza Integration

This branch is the integration landing zone for `{repo.upstream}`.

The first pass keeps upstream source untouched and records the build graph
features Azazel and Zaza need to model before attempting a full replacement.

Current focus:

- Zig toolchain lane detection
- package dependency diagnostics
- module-only targets
- generated-source steps
- native link metadata
- corpus parity reporting
- build-proof reporting
- actionable build diagnostics
""",
        encoding="utf-8",
    )
    (overlay / "project.cue").write_text(
        """package build

toolchain: zig: {
    lanes: ["0.14", "0.15", "0.16"]
    preferred: "%s"
}
"""
        % cue_preferred_lane(repo)
        + system_deps_cue(repo),
        encoding="utf-8",
    )
    write_executable_parity_workspace(path, repo)


def system_deps_cue(repo: Repo) -> str:
    """The repo's host requirements as a `system_deps` declaration."""
    if not repo.requirements:
        return ""
    lines = ["", "system_deps: ["]
    lines.extend(f"    {item.cue()}," for item in repo.requirements)
    lines.append("]")
    return "\n".join(lines) + "\n"


def write_executable_parity_workspace(path: Path, repo: Repo) -> None:
    if repo.executable_parity_status != "ready":
        return

    workspace = path / ".azazel" / "parity-work"
    workspace.mkdir(parents=True, exist_ok=True)
    generated_spec = workspace / "build_spec.zig"
    if generated_spec.exists():
        generated_spec.unlink()
    azazel_root = Path(__file__).resolve().parents[1]
    for name in ("build.zig", "schema.cue", "gen_build_spec.sh", "build_spec_test.zig", "compat.zig"):
        shutil.copy2(azazel_root / name, workspace / name)

    src_dir = workspace / "src"
    src_dir.mkdir(exist_ok=True)
    (workspace / ".gitignore").write_text("build_spec.zig\nzig-cache/\nzig-out/\nzig-pkg/\n", encoding="utf-8")
    if repo.name == "libxev":
        (workspace / "project.cue").write_text(
            """package build

toolchain: zig: {
    lanes: ["0.16"]
    preferred: "0.16"
}

xev: #Module & {
    kind: "module"
    root: "../../src/main.zig"
}

xev_probe: #Module & {
    kind: "exe"
    root: "src/xev_probe.zig"
    deps: ["xev"]
    link: "import"
}
""",
            encoding="utf-8",
        )
        write_standard_export(workspace, ("xev", "xev_probe"))
        (src_dir / "xev_probe.zig").write_text(
            """const xev = @import("xev");

pub fn main() void {
    _ = xev.Backend;
    _ = xev.Loop;
}
""",
            encoding="utf-8",
        )
        return

    if repo.name == "libvaxis":
        # The slice takes zigimg and uucode exactly as upstream pins them: the
        # same aliases, urls, hashes and lazy flags, read from its build.zig.zon.
        upstream = upstream_packages(path, ("zigimg", "uucode"))
        (workspace / "project.cue").write_text(
            """package build

toolchain: zig: {
    lanes: ["0.16"]
    preferred: "0.16"
}

"""
            + packages_cue(upstream)
            + """
vaxis: #Module & {
    kind: "module"
    root: "../../src/main.zig"
    pkg_imports: [
        {
            alias: "zigimg"
            package: "zigimg"
            module: "zigimg"
        },
        {
            alias: "uucode"
            package: "uucode"
            module: "uucode"
            args: _uucode_args
        },
    ]
}

// The Unicode property tables upstream asks uucode to build, as a string-list
// option of uucode's build function.
_uucode_args: [{
    name: "fields"
    kind: "string_list"
    value: ["east_asian_width", "grapheme_break", "general_category", "is_emoji_presentation"]
}]

// uucode compiles and runs `uucode_generate`, then exports the tables it wrote
// as the named path "tables.zig". Declaring it here makes that run-artifact
// output a tracked file of this slice: it is installed, and the probe embeds it.
generated: unicode_tables: {
    package: {
        package: "uucode"
        named_path: "tables.zig"
        args: _uucode_args
    }
    outputs: [{name: "tables.zig", install: "share/vaxis/unicode_tables.zig"}]
}

vaxis_probe: #Module & {
    kind: "exe"
    root: "src/vaxis_probe.zig"
    deps: ["vaxis"]
    link: "import"
    generated: [{from: "unicode_tables", output: "tables.zig", as: "embed", alias: "unicode_tables"}]
}
""",
            encoding="utf-8",
        )
        write_standard_export(workspace, ("vaxis", "vaxis_probe"))
        write_workspace_zon(
            workspace,
            ".vaxis_azazel_parity",
            {dep.alias: {"url": dep.url, "hash": dep.hash, "lazy": dep.lazy} for dep in upstream},
        )
        (src_dir / "vaxis_probe.zig").write_text(
            """const vaxis = @import("vaxis");

const unicode_tables = @embedFile("unicode_tables");

pub fn main() void {
    _ = vaxis.Vaxis;
    _ = vaxis.Key;
    _ = vaxis.zigimg.Image;
    if (unicode_tables.len == 0) @panic("generated Unicode tables are empty");
}
""",
            encoding="utf-8",
        )
        return

    if repo.name == "zig-gamedev":
        (workspace / "project.cue").write_text(
            """package build

toolchain: zig: {
    lanes: ["0.15"]
    preferred: "0.15"
}

packages: {
    zmath: {
        path: "../../zig-pkg/zmath-0.11.0-dev-wjwivdMsAwD-xaLj76YHUq3t9JDH-X16xuMTmnDzqbu2"
    }
    zglfw: {
        path: "../../zig-pkg/zglfw-0.10.0-dev-zgVDNIG4IQBWN_sfMD-xfC9bJS2hbBN2W7jNlDLovcdC"
    }
    zopengl: {
        path: "../../zig-pkg/zopengl-0.6.0-dev-5-tnz36mDgBuU9pDfag6_B-qCWOJQc5GXiXuZ6z41zQM"
    }
    zmesh: {
        path: "../../zig-pkg/zmesh-0.11.0-dev-oO3A5lKRCgCGK8Krro4Rj_F_MhO8LT487re5u_DNIzvl"
    }
    znoise: {
        path: "../../zig-pkg/znoise-0.3.0-dev-gK1op9ikAQDrS4G22GluyaQaabjGzhdnhV2QyCoLE8z7"
    }
    zgui: {
        path: "../../zig-pkg/zgui-0.6.0-dev--L6sZKkSbgCUBXLVfwJDPpMkETz7ll-mmQYQae-nMxjt"
    }
    zgpu: {
        path: "../../zig-pkg/zgpu-0.12.0-dev-UxK2DAfAzgAdcCqFsXIj2RZRQFuLFhzr9C-s91Hm0U0q"
    }
    dawn_aarch64_macos: {
        url: "https://github.com/michal-z/webgpu_dawn-aarch64-macos/archive/d2360cdfff0cf4a780cb77aa47c57aca03cc6dfe.tar.gz"
        hash: "N-V-__8AALVIRAIf5nfpx8-4mEo2RGsynVryPQPcHk95qFM5"
        lazy: true
    }
}

// Options for zgui's build function, as upstream's frame_pacing_wgpu sample
// passes them: an enum backend and a bool. The import and the artifact take
// the same list, so both resolve to one dependency.
_zgui_args: [
    {name: "backend", kind: "enum", value: "glfw_wgpu"},
    {name: "with_implot", kind: "bool", value: true},
]

// Integer and bool options of zgpu's build function, set to zgpu's own
// defaults. They pass through the same mechanism as any other option.
_zgpu_args: [
    {name: "uniforms_buffer_size", kind: "int", value: 4194304},
    {name: "buffer_pool_size", kind: "int", value: 256},
    {name: "dawn_skip_validation", kind: "bool", value: false},
]

zig_gamedev_vectormath: #Module & {
    kind: "module"
    root: "../../samples/common/src/vectormath.zig"
}

zig_gamedev_vectormath_probe: #Module & {
    kind: "exe"
    root: "src/zig_gamedev_vectormath_probe.zig"
    deps: ["zig_gamedev_vectormath"]
    link: "import"
    pkg_imports: [{
        alias: "zmath"
        package: "zmath"
        module: "root"
    }, {
        alias: "zglfw"
        package: "zglfw"
        module: "root"
        pass_optimize: false
    }, {
        alias: "zopengl"
        package: "zopengl"
        module: "root"
        pass_optimize: false
    }, {
        alias: "zmesh"
        package: "zmesh"
        module: "root"
    }, {
        alias: "znoise"
        package: "znoise"
        module: "root"
    }, {
        alias: "zgui"
        package: "zgui"
        module: "root"
        args: _zgui_args
    }, {
        alias: "zgpu"
        package: "zgpu"
        module: "root"
        args: _zgpu_args
    }]
    pkg_artifacts: [{
        package: "zglfw"
        artifact: "glfw"
        pass_optimize: false
    }, {
        package: "zmesh"
        artifact: "zmesh"
    }, {
        package: "znoise"
        artifact: "FastNoiseLite"
    }, {
        package: "zgui"
        artifact: "imgui"
        args: _zgui_args
    }, {
        package: "zgpu"
        artifact: "zdawn"
        args: _zgpu_args
    }]
    pkg_library_paths: [{
        package: "dawn_aarch64_macos"
        os: "macos"
        arch: "aarch64"
    }]
    native: {
        system_libs: ["dawn"]
    }
    install_dirs: [{
        source_dir: "../../samples/sdl2_demo/sdl2_demo_content"
        install_dir: "bin"
        install_subdir: "sdl2_demo_content"
    }]
}
""",
            encoding="utf-8",
        )
        write_standard_export(workspace, ("zig_gamedev_vectormath", "zig_gamedev_vectormath_probe"))
        write_workspace_zon(
            workspace,
            ".zig_gamedev_azazel_parity",
            {
                "zmath": "../../zig-pkg/zmath-0.11.0-dev-wjwivdMsAwD-xaLj76YHUq3t9JDH-X16xuMTmnDzqbu2",
                "zglfw": "../../zig-pkg/zglfw-0.10.0-dev-zgVDNIG4IQBWN_sfMD-xfC9bJS2hbBN2W7jNlDLovcdC",
                "zopengl": "../../zig-pkg/zopengl-0.6.0-dev-5-tnz36mDgBuU9pDfag6_B-qCWOJQc5GXiXuZ6z41zQM",
                "zmesh": "../../zig-pkg/zmesh-0.11.0-dev-oO3A5lKRCgCGK8Krro4Rj_F_MhO8LT487re5u_DNIzvl",
                "znoise": "../../zig-pkg/znoise-0.3.0-dev-gK1op9ikAQDrS4G22GluyaQaabjGzhdnhV2QyCoLE8z7",
                "zgui": "../../zig-pkg/zgui-0.6.0-dev--L6sZKkSbgCUBXLVfwJDPpMkETz7ll-mmQYQae-nMxjt",
                "zgpu": "../../zig-pkg/zgpu-0.12.0-dev-UxK2DAfAzgAdcCqFsXIj2RZRQFuLFhzr9C-s91Hm0U0q",
                "dawn_aarch64_macos": {
                    "url": "https://github.com/michal-z/webgpu_dawn-aarch64-macos/archive/d2360cdfff0cf4a780cb77aa47c57aca03cc6dfe.tar.gz",
                    "hash": "N-V-__8AALVIRAIf5nfpx8-4mEo2RGsynVryPQPcHk95qFM5",
                    "lazy": True,
                },
            },
            fingerprint="0x28185f0b3b82664a",
        )
        (src_dir / "zig_gamedev_vectormath_probe.zig").write_text(
            """const vectormath = @import("zig_gamedev_vectormath");
const zmath = @import("zmath");
const zglfw = @import("zglfw");
const zopengl = @import("zopengl");
const zmesh = @import("zmesh");
const znoise = @import("znoise");
const zgui = @import("zgui");
const zgpu = @import("zgpu");

pub fn main() void {
    const a = vectormath.Vec3.init(1.0, 2.0, 3.0);
    const b = vectormath.Vec3.init(4.0, 5.0, 6.0);
    const dot = vectormath.Vec3.dot(a, b);
    if (dot != 32.0) @panic("unexpected vectormath result");
    _ = vectormath.Mat4.initTranslation(a);
    _ = zmath.translation(1.0, 2.0, 3.0);
    _ = zglfw.Window;
    _ = zopengl.Extension.KHR_debug;
    _ = zmesh.io;
    _ = znoise.FnlGenerator;
    _ = zgui.backend;
    _ = zgui.DrawVert;
    _ = zgpu.GraphicsContext;
}
""",
            encoding="utf-8",
        )
        return

    raise SystemExit(f"repo {repo.name} declares executable parity but has no workspace writer")


def upstream_packages(path: Path, aliases: tuple[str, ...]) -> list[zon.Dependency]:
    """The named dependencies of the repo's own build.zig.zon, as upstream pins them."""
    manifest = path / "build.zig.zon"
    if not manifest.is_file():
        raise SystemExit(f"{path}: no build.zig.zon to read package dependencies from")
    found = {dep.alias: dep for dep in zon.read_dependencies(manifest.read_text(encoding="utf-8"))}
    missing = [alias for alias in aliases if alias not in found]
    if missing:
        raise SystemExit(f"{manifest}: no dependency named {', '.join(missing)}")
    return [found[alias] for alias in aliases]


def packages_cue(deps: list[zon.Dependency]) -> str:
    return zon.render_cue_packages(deps)


def write_standard_export(workspace: Path, modules: tuple[str, ...]) -> None:
    module_lines = "".join(f'    "{name}": {name}\n' for name in modules)
    (workspace / "export.cue").write_text(
        """package build

_modules: {
"""
        + module_lines
        + """}

_toolchain: toolchain
_packages: packages
_options: options
_system_deps: system_deps
_generated: generated
_subprojects: subprojects

build: modules: {
    for k, v in _modules {
        (k): {
            kind: v.kind
            root: v.root
            subproject: v.subproject
            deps: v.deps
            link: v.link
            pre: v.pre
            post: v.post
            install_dirs: v.install_dirs
            pkg_library_paths: v.pkg_library_paths
            pkg_imports: v.pkg_imports
            pkg_artifacts: v.pkg_artifacts
            generated: v.generated
            build_options: v.build_options
            build_options_import: v.build_options_import
            native: v.native
            optimize: profiles[v.profile].optimize
        }
    }
}

build: toolchain: _toolchain
build: packages: _packages
build: options: _options
build: system_deps: _system_deps
build: generated: _generated
build: subprojects: _subprojects
""",
        encoding="utf-8",
    )


def write_workspace_zon(
    workspace: Path,
    package_name: str,
    deps: dict[str, str | dict[str, object]],
    fingerprint: str = "0x556db0b97b71fd4c",
) -> None:
    lines = [
        ".{",
        f"    .name = {package_name},",
        '    .version = "0.0.0",',
        f"    .fingerprint = {fingerprint},",
        "    .dependencies = .{",
    ]
    rendered = zon.render_dependencies(
        [
            zon.Dependency(alias=name, path=dep)
            if isinstance(dep, str)
            else zon.Dependency(
                alias=name,
                url=str(dep.get("url", "")),
                hash=str(dep.get("hash", "")),
                path=str(dep.get("path", "")),
                lazy=bool(dep.get("lazy", False)),
            )
            for name, dep in deps.items()
        ]
    )
    lines[-1] = "    .dependencies = " + rendered + ","
    lines.extend(
        [
            "    .paths = .{",
            '        "build.zig",',
            '        "build.zig.zon",',
            '        "build_spec_test.zig",',
            '        "compat.zig",',
            '        "schema.cue",',
            '        "project.cue",',
            '        "export.cue",',
            '        "gen_build_spec.sh",',
            '        "src",',
            "    },",
            "}",
            "",
        ]
    )
    (workspace / "build.zig.zon").write_text("\n".join(lines), encoding="utf-8")


def ensure_git_package(dest: Path, url: str, ref: str) -> None:
    if (dest / ".git").exists():
        run(["git", "fetch", "--tags", "origin", ref], cwd=dest, check=False)
        run(["git", "checkout", "--force", ref], cwd=dest)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--filter=blob:none", url, str(dest)])
    run(["git", "checkout", "--force", ref], cwd=dest)


def materialize_executable_parity_deps(path: Path, repo: Repo) -> None:
    if repo.name == "zig-gamedev":
        pkg_root = path / "zig-pkg"
        ensure_git_package(
            pkg_root / "zmath-0.11.0-dev-wjwivdMsAwD-xaLj76YHUq3t9JDH-X16xuMTmnDzqbu2",
            "https://github.com/zig-gamedev/zmath.git",
            "3a5955b2b72cd081563fbb084eff05bffd1e3fbb",
        )
        ensure_git_package(
            pkg_root / "zglfw-0.10.0-dev-zgVDNIG4IQBWN_sfMD-xfC9bJS2hbBN2W7jNlDLovcdC",
            "https://github.com/zig-gamedev/zglfw.git",
            "0dd29d8073487c9fe1e45e6b729b3aac271d5a71",
        )
        ensure_git_package(
            pkg_root / "zopengl-0.6.0-dev-5-tnz36mDgBuU9pDfag6_B-qCWOJQc5GXiXuZ6z41zQM",
            "https://github.com/zig-gamedev/zopengl.git",
            "db9d615c742086b39954eef064f957e92dafc7e2",
        )
        ensure_git_package(
            pkg_root / "zmesh-0.11.0-dev-oO3A5lKRCgCGK8Krro4Rj_F_MhO8LT487re5u_DNIzvl",
            "https://github.com/zig-gamedev/zmesh.git",
            "a9c23ba7440b8c03cbc2bec89a3285fe84cbb50f",
        )
        ensure_git_package(
            pkg_root / "znoise-0.3.0-dev-gK1op9ikAQDrS4G22GluyaQaabjGzhdnhV2QyCoLE8z7",
            "https://github.com/zig-gamedev/znoise.git",
            "01c8b354cc3ef7f2293de75e58d3298a77d7ed06",
        )
        ensure_git_package(
            pkg_root / "zgui-0.6.0-dev--L6sZKkSbgCUBXLVfwJDPpMkETz7ll-mmQYQae-nMxjt",
            "https://github.com/zig-gamedev/zgui.git",
            "ce016156a8520c438e886cd6c0b605e10ee7af3d",
        )
        ensure_git_package(
            pkg_root / "zgpu-0.12.0-dev-UxK2DAfAzgAdcCqFsXIj2RZRQFuLFhzr9C-s91Hm0U0q",
            "https://github.com/zig-gamedev/zgpu.git",
            "c512b60c1f0cd438dcc6297083d0e3d91ad5e717",
        )
        return

    # libvaxis needs nothing here: its slice declares url and hash, and Zig
    # fetches both packages itself.


def select_repos(names: list[str]) -> list[Repo]:
    if not names:
        return REPOS
    wanted = set(names)
    selected = [repo for repo in REPOS if repo.name in wanted or repo.upstream in wanted or repo.fork in wanted]
    found = {repo.name for repo in selected} | {repo.upstream for repo in selected} | {repo.fork for repo in selected}
    missing = sorted(wanted - found)
    if missing:
        known = ", ".join(repo.name for repo in REPOS)
        raise SystemExit(f"unknown repo(s): {', '.join(missing)}\nknown repos: {known}")
    return selected


def expected_matches(classification: str, expected: str) -> bool | None:
    if expected == "unverified":
        return None
    return classification == expected


def repo_plan_entry(repo: Repo) -> dict[str, object]:
    doctor = doctor_entry(repo)
    return {
        "name": repo.name,
        "upstream": repo.upstream,
        "fork": repo.fork,
        "branch": BRANCH,
        "notes": repo.notes,
        "integration_kind": repo.integration_kind,
        "preferred_zig": repo.preferred_zig,
        "build_zig": repo.build_zig,
        "toolchain": doctor["toolchain"],
        "doctor_ready": doctor["ready"],
        "doctor_missing": doctor["missing"],
        "baseline_command": list(repo.baseline_command),
        "expected_baseline_classification": repo.expected_classification,
        "build_command": list(repo.build_command),
        "expected_build_classification": repo.expected_build_classification,
        "azazel_status": repo.parity_status,
        "azazel_command": list(repo.azazel_command),
        "executable_parity_status": repo.executable_parity_status,
        "executable_parity_targets": list(repo.executable_parity_targets),
        "first_targets": list(repo.first_targets),
        "system_deps": list(repo.system_deps),
        "required_tools": list(repo.required_tools),
        "pkg_config_libs": list(repo.pkg_config_libs),
        "replacement_gaps": list(repo.replacement_gaps),
        "target_slices": [item.manifest() for item in repo.target_slices],
        "next_action": doctor["next_action"],
    }


def markdown_list(items: list[object] | tuple[str, ...]) -> str:
    if not items:
        return "- none\n"
    return "".join(f"- `{item}`\n" for item in items)


def roadmap_issue_body(entry: dict[str, object]) -> str:
    name = str(entry["name"])
    return (
        f"# Replace upstream build slice for `{name}`\n\n"
        "## Source\n\n"
        f"- upstream: `{entry['upstream']}`\n"
        f"- fork: `{entry['fork']}`\n"
        f"- integration branch: `{entry['branch']}`\n"
        f"- notes: {entry['notes']}\n\n"
        "## Current proof state\n\n"
        f"- preferred Zig lane: `{entry['preferred_zig']}`\n"
        f"- build Zig lane: `{entry['build_zig']}`\n"
        f"- doctor ready: `{entry['doctor_ready']}`\n"
        f"- missing prerequisites: {', '.join(f'`{item}`' for item in entry['doctor_missing']) or 'none'}\n"
        f"- expected baseline classification: `{entry['expected_baseline_classification']}`\n"
        f"- expected build classification: `{entry['expected_build_classification']}`\n"
        f"- Azazel parity status: `{entry['azazel_status']}`\n"
        f"- executable parity status: `{entry['executable_parity_status']}`\n\n"
        "## First target slice\n\n"
        f"{markdown_list(entry['first_targets'])}\n"
        "## Replacement gaps\n\n"
        f"{markdown_list(entry['replacement_gaps'])}\n"
        "## Host/system prerequisites\n\n"
        "Required tools:\n\n"
        f"{markdown_list(entry['required_tools'])}\n"
        "Pkg-config libraries:\n\n"
        f"{markdown_list(entry['pkg_config_libs'])}\n"
        "System dependencies:\n\n"
        f"{markdown_list(entry['system_deps'])}\n"
        "## Next action\n\n"
        f"{entry['next_action']}\n\n"
        "## Acceptance criteria\n\n"
        "- `tools/huge_corpus.py --doctor --repo "
        f"{name}` reports the declared prerequisites accurately\n"
        "- `tools/huge_corpus.py --build --repo "
        f"{name}` matches the declared expected build classification\n"
        "- the first target slice has either executable Azazel parity or an updated manifest explaining why it is not modeled yet\n"
        "- docs and generated site output describe the new replacement boundary without claiming full build parity prematurely\n"
    )


def roadmap(root: Path, repos: list[Repo], expect_count: int | None) -> None:
    entries = [repo_plan_entry(repo) for repo in repos]
    issue_dir = root / "corpus-issues"
    issue_dir.mkdir(parents=True, exist_ok=True)

    gap_counts: dict[str, int] = {}
    for entry in entries:
        for gap in entry["replacement_gaps"]:
            gap_counts[str(gap)] = gap_counts.get(str(gap), 0) + 1

    issue_links = []
    for entry in entries:
        name = str(entry["name"])
        issue_path = issue_dir / f"{name}.md"
        issue_path.write_text(roadmap_issue_body(entry), encoding="utf-8")
        issue_links.append((name, issue_path.relative_to(root)))

    summary = {
        "repo_count": len(entries),
        "expected_count": expect_count,
        "count_matches": None if expect_count is None else len(entries) == expect_count,
        "doctor_ready": sum(1 for entry in entries if entry["doctor_ready"]),
        "doctor_blocked": sum(1 for entry in entries if not entry["doctor_ready"]),
        "executable_parity_ready": sum(1 for entry in entries if entry["executable_parity_status"] == "ready"),
    }
    lines = [
        "# Azazel/Zaza 10-Repo Replacement Roadmap",
        "",
        "This roadmap is generated from the same corpus manifests used by",
        "`tools/huge_corpus.py --plan`. It records replacement work without",
        "claiming full-project parity for repos whose Azazel slice is still",
        "`scaffold-only` or `not-modeled`.",
        "",
        "## Summary",
        "",
        f"- repos: `{summary['repo_count']}`",
        f"- expected count: `{summary['expected_count']}`",
        f"- count matches: `{summary['count_matches']}`",
        f"- doctor ready: `{summary['doctor_ready']}`",
        f"- doctor blocked: `{summary['doctor_blocked']}`",
        f"- executable parity slices ready: `{summary['executable_parity_ready']}`",
        "",
        "## Cross-Repo Gap Clusters",
        "",
    ]
    if gap_counts:
        for gap, count in sorted(gap_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{gap}`: {count} repo(s)")
    else:
        lines.append("- none")
    lines.extend(["", "## Repo Issues", ""])
    for name, path in issue_links:
        lines.append(f"- [`{name}`]({path})")
    lines.extend(["", "## Batch Commands", ""])
    lines.extend(
        [
            "```sh",
            "tools/huge_corpus.py --plan --expect-count 10",
            "tools/huge_corpus.py --roadmap --expect-count 10",
            "tools/huge_corpus.py --doctor --expect-count 10",
            "tools/huge_corpus.py --build --expect-count 10",
            "tools/huge_corpus.py --executable-parity --expect-count 10",
            "```",
            "",
        ]
    )
    (root / "corpus-roadmap.md").write_text("\n".join(lines), encoding="utf-8")
    status = "ok" if summary["count_matches"] is not False else "mismatch"
    print(f"roadmap {status}: wrote corpus-roadmap.md and {len(issue_links)} issue files")


def plan(root: Path, repos: list[Repo], expect_count: int | None) -> None:
    entries = [repo_plan_entry(repo) for repo in repos]
    summary = {
        "repo_count": len(entries),
        "expected_count": expect_count,
        "count_matches": None if expect_count is None else len(entries) == expect_count,
        "doctor_ready": sum(1 for entry in entries if entry["doctor_ready"]),
        "doctor_blocked": sum(1 for entry in entries if not entry["doctor_ready"]),
        "executable_parity_ready": sum(1 for entry in entries if entry["executable_parity_status"] == "ready"),
        "unverified_baselines": sum(
            1
            for entry in entries
            if entry["expected_baseline_classification"] == "unverified"
            or entry["expected_build_classification"] == "unverified"
        ),
    }
    report = {
        "schema": 1,
        "branch": BRANCH,
        "summary": summary,
        "repos": entries,
        "commands": {
            "prepare": "tools/huge_corpus.py --prepare --push --expect-count 10",
            "roadmap": "tools/huge_corpus.py --roadmap --expect-count 10",
            "doctor": "tools/huge_corpus.py --doctor --expect-count 10",
            "build": "tools/huge_corpus.py --build --expect-count 10",
            "parity": "tools/huge_corpus.py --parity --expect-count 10",
            "executable_parity": "tools/huge_corpus.py --executable-parity --expect-count 10",
        },
    }
    (root / "corpus-plan.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    status = "ok" if summary["count_matches"] is not False else "mismatch"
    print(
        f"plan {status}: {summary['repo_count']} repos; "
        f"{summary['doctor_ready']} doctor-ready; "
        f"{summary['executable_parity_ready']} executable parity slices; "
        f"{summary['unverified_baselines']} unverified baselines"
    )


def push_integration_branch(path: Path, refresh_base: bool) -> None:
    if not refresh_base:
        run(["git", "push", "-u", "origin", BRANCH], cwd=path)
        return

    for attempt in range(2):
        lease_result = run(["git", "ls-remote", "origin", BRANCH], cwd=path, check=False)
        lease = lease_result.stdout.split()[0] if lease_result.returncode == 0 and lease_result.stdout.strip() else ""
        if lease:
            push_cmd = ["git", "push", "-u", f"--force-with-lease={BRANCH}:{lease}", "origin", BRANCH]
        else:
            push_cmd = ["git", "push", "-u", "origin", BRANCH]
        result = run(push_cmd, cwd=path, check=False)
        if result.returncode == 0:
            return
        if attempt == 0 and "stale info" in result.stdout:
            continue
        raise SystemExit(
            f"command failed ({result.returncode}) in {path}:\n"
            f"{' '.join(push_cmd)}\n{result.stdout}"
        )


def prepare(root: Path, repos: list[Repo], push: bool, refresh_base: bool) -> None:
    for repo in repos:
        path = ensure_clone(root, repo)
        if refresh_base:
            refresh_branch_base(path)
        else:
            checkout_branch(path)
        write_overlay(path, repo)
        run(["git", "add", "-f", ".azazel"], cwd=path)
        staged = run(["git", "diff", "--cached", "--quiet"], cwd=path, check=False)
        if staged.returncode:
            run(["git", "commit", "-m", "Add Azazel/Zaza integration scaffold"], cwd=path)
        if push:
            push_integration_branch(path, refresh_base)
        print(f"{repo.name}: prepared")


def audit(root: Path, repos: list[Repo]) -> None:
    report = []
    for repo in repos:
        path = ensure_clone(root, repo)
        result = run(["zig", "build", "--help"], cwd=path, check=False)
        output = result.stdout[-OUTPUT_TAIL_BYTES:]
        report.append(
            {
                "name": repo.name,
                "returncode": result.returncode,
                "classification": classify_failure(output, result.returncode),
                "output": output,
            }
        )
        print(f"{repo.name}: zig build --help -> {result.returncode}")
    (root / "audit-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def command_with_zig(command: list[str], zig: str) -> list[str]:
    if command and command[0] == "zig":
        return [zig] + command[1:]
    return command


def pkg_config_available(name: str, min_version: str = "") -> bool:
    if not shutil.which("pkg-config"):
        return False
    command = ["pkg-config", "--exists"]
    if min_version:
        command.append(f"--atleast-version={min_version}")
    return subprocess.run(
        command + [name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).returncode == 0


def host_os() -> str:
    return zig_toolchain.host_platform().split("-", 1)[1]


def system_preflight(repo: Repo) -> dict[str, object]:
    """Probe the repo's declared host requirements without building anything.

    Tools and pkg-config libraries are probed here. The other kinds need a
    compiler probe, which the generated build runs through `zig build doctor`;
    they are recorded with `checked: false` and never counted as missing.
    """
    current_os = host_os()
    results = []
    for item in repo.requirements:
        entry = item.manifest()
        applies = not item.os or current_os in item.os
        entry.update({"applies": applies, "checked": False, "found": None, "detail": ""})
        if not applies:
            entry["detail"] = f"not required on {current_os}"
        elif item.kind == "tool":
            path = shutil.which(item.name) or ""
            entry.update({"checked": True, "found": bool(path), "detail": path or "not found on PATH"})
        elif item.kind == "pkg_config":
            found = pkg_config_available(item.name, item.min_version)
            if found:
                detail = "found by pkg-config"
            elif not shutil.which("pkg-config"):
                detail = "pkg-config is not on PATH"
            else:
                detail = "not known to pkg-config"
            entry.update({"checked": True, "found": found, "detail": detail})
        else:
            entry["detail"] = "probed by zig build doctor in a generated build"
        results.append(entry)
    missing = [entry for entry in results if entry["checked"] and not entry["found"]]
    lines = []
    for entry in missing:
        label = "pkg-config library" if entry["kind"] == "pkg_config" else entry["kind"]
        line = f"missing declared system requirement: {label} {entry['name']} ({entry['detail']})"
        if entry.get("hint"):
            line += f"; {entry['hint']}"
        lines.append(line)
    return {
        "ready": not missing,
        "requirements": results,
        "missing": [f"{'pkg-config' if entry['kind'] == 'pkg_config' else entry['kind']}:{entry['name']}" for entry in missing],
        "diagnostic": "\n".join(lines),
    }


def doctor_entry(repo: Repo) -> dict[str, object]:
    resolution = resolve_toolchain(repo)
    zig = resolution.path
    preflight = system_preflight(repo)
    tools = [
        {"name": entry["name"], "path": entry["detail"] if entry["found"] else "", "found": bool(entry["found"])}
        for entry in preflight["requirements"]
        if entry["kind"] == "tool" and entry["applies"]
    ]
    pkg_config = [
        {"name": entry["name"], "found": bool(entry["found"])}
        for entry in preflight["requirements"]
        if entry["kind"] == "pkg_config" and entry["applies"]
    ]
    ready = bool(zig) and preflight["ready"]
    missing = []
    if not zig:
        missing.append(f"zig:{repo.build_zig}")
    blocked = resolution.status if not zig else "doctor-blocked"
    missing.extend(preflight["missing"])
    return {
        "name": repo.name,
        "ready": ready,
        "missing": missing,
        "toolchain": resolution.as_dict(),
        "required_tools": tools,
        "pkg_config_libs": pkg_config,
        "requirements": preflight["requirements"],
        "system_deps": list(repo.system_deps),
        "first_targets": list(repo.first_targets),
        "replacement_gaps": list(repo.replacement_gaps),
        "next_action": next_action(
            repo,
            repo.expected_build_classification if ready else blocked,
            resolution.diagnostic,
        ),
    }


def doctor(root: Path, repos: list[Repo]) -> None:
    report = [doctor_entry(repo) for repo in repos]
    for entry in report:
        status = "ready" if entry["ready"] else "blocked"
        missing = ", ".join(entry["missing"]) if entry["missing"] else "none"
        print(f"{entry['name']}: doctor {status}; missing: {missing}")
        if not entry["toolchain"]["found"]:
            print(f"  toolchain: {entry['toolchain']['diagnostic']}")
    (root / "doctor-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def next_action(repo: Repo, classification: str, output: str) -> str:
    if classification == "ok":
        if repo.parity_status == "ready":
            return "run the declared Azazel parity command and compare artifacts"
        return "implement the first Azazel target slice: " + ", ".join(repo.first_targets)
    if classification == "doctor-blocked":
        return "install or configure the missing toolchain/tools before running build proof"
    if classification == "zig-toolchain":
        if repo.name == "zls":
            return "pin an accepted ZLS 0.17-dev build or track the ZLS toolchain window before parity work"
        return "resolve the project Zig lane before modeling build graph parity"
    if classification in (zig_toolchain.MISSING, zig_toolchain.UNSUPPORTED, zig_toolchain.FETCH_FAILED):
        spec = repo.required_toolchain()
        if classification == zig_toolchain.UNSUPPORTED:
            return f"replace the local build with {spec.requirement()}, or set {spec.env_key}"
        if classification == zig_toolchain.FETCH_FAILED:
            return f"no index or mirror served {spec.requirement()}; install it by hand and set {spec.env_key}"
        return f"install {spec.requirement()}, set {spec.env_key}, or rerun with --fetch-toolchains"
    if classification == "system-dependency":
        missing = system_preflight(repo)["missing"]
        deps = ", ".join(missing or repo.system_deps or repo.required_tools)
        return f"install host system dependencies, then rerun --doctor and --build: {deps}"
    if classification == "dependency-fetch":
        return "fix dependency archive/cache fetching before translating the target slice"
    if classification == "dependency-format":
        return "patch or pin the transitive dependency to a package format accepted by the declared Zig lane"
    if classification == "zig-api-drift":
        return "try the next Zig lane or pin upstream dependencies before claiming replacement parity"
    if classification == "platform-package":
        return "split package/app-bundle steps from core build, then model resource and platform packaging edges"
    if classification == "missing-lfs-content":
        return "fetch Git LFS content or refresh the integration branch from upstream"
    return "inspect build output and add a stable classification before continuing"


# Set by --package-cache. When given, every build shares this Zig global cache,
# so a fresh clone root reuses packages that were already fetched.
PACKAGE_CACHE: Path | None = None


def build_cache_roots(root: Path, repo: Repo) -> dict[str, str]:
    safe_name = repo.name.replace("-", "_")
    shared = PACKAGE_CACHE
    return {
        "global": str(shared if shared is not None else root / f".zig-cache-{safe_name}-{repo.build_zig}"),
        "local": str(root / f".zig-cache-local-{safe_name}-{repo.build_zig}"),
    }


def portable_path(path: str, root: Path) -> str:
    """A path with the clone root written as `<root>` and the shared cache as `<package-cache>`."""
    prefixes = [(str(root.resolve()), "<root>"), (str(root), "<root>")]
    if PACKAGE_CACHE is not None:
        prefixes.insert(0, (str(PACKAGE_CACHE), "<package-cache>"))
    for prefix, name in prefixes:
        if path == prefix or path.startswith(prefix + os.sep):
            return name + path[len(prefix):]
    return path


def portable_text(text: str, root: Path, repo: Repo) -> str:
    """Build output with machine-specific locations replaced.

    The clone root becomes `<root>`, the shared package cache `<package-cache>`
    and the toolchain directory `<zig>`. Two runs from different clone roots
    then differ only in what Zig itself randomises.
    """
    replacements = [(str(root.resolve()), "<root>"), (str(root), "<root>")]
    if PACKAGE_CACHE is not None:
        replacements.append((str(PACKAGE_CACHE.resolve()), "<package-cache>"))
        replacements.append((str(PACKAGE_CACHE), "<package-cache>"))
    resolution = _RESOLUTIONS.get(repo.required_toolchain().id)
    if resolution is not None and resolution.path:
        replacements.append((str(Path(resolution.path).parent), "<zig>"))
    for old, new in sorted(replacements, key=lambda item: -len(item[0])):
        text = text.replace(old, new)
    # Zig unpacks each fetched archive under a randomly named directory.
    return re.sub(r"/tmp/[0-9a-f]{16}(?=/)", "/tmp/<random>", text)


def dependencies_report(root: Path, repos: list[Repo]) -> None:
    """Write the package dependency metadata of each repo, without building."""
    report = []
    for repo in repos:
        path = ensure_clone(root, repo)
        info = corpus_deps.describe(path)
        report.append({"name": repo.name, **info})
        summary = info["summary"]
        if info.get("manifest") is None:
            print(f"{repo.name}: no build.zig.zon")
        elif "error" in info:
            print(f"{repo.name}: {info['error']}")
        else:
            sources = ", ".join(f"{count} {source}" for source, count in summary["by_source"].items()) or "none"
            print(f"{repo.name}: {summary['count']} dependencies ({sources}); {summary['lazy']} lazy")
            if summary["nested_count"]:
                nested = ", ".join(f"{count} {source}" for source, count in summary["nested_by_source"].items())
                print(f"  {summary['nested_count']} more in nested path packages ({nested})")
            everything = info["dependencies"] + info["nested_dependencies"]
            legacy = sorted({entry["alias"] for entry in everything if entry["hash_format"] == "legacy-multihash"})
            if legacy:
                print(f"  pinned in the pre-0.14 hash format: {', '.join(legacy)}")
    (root / "dependencies-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run_build(root: Path, repos: list[Repo]) -> None:
    report = []
    for repo in repos:
        # Resolve the toolchain before cloning. A repo whose required Zig is
        # absent is reported from the manifest alone.
        resolution = resolve_toolchain(repo)
        zig = resolution.path
        preflight = system_preflight(repo)
        dependencies: dict[str, object] = {}
        diagnosis: dict[str, object] | None = None
        cache_roots: dict[str, object] = {}
        target_slice: list[dict[str, object]] = []
        slice_expected = ""
        slice_matches: bool | None = None
        if not zig:
            classification = resolution.status
            output = resolution.diagnostic
            returncode = 127
            command = list(repo.build_command)
        elif not preflight["ready"]:
            # A declared requirement is absent. Report it as such and do not
            # start a build that can only fail on it.
            classification = "system-dependency"
            output = str(preflight["diagnostic"])
            returncode = 127
            command = command_with_zig(list(repo.build_command), zig)
        else:
            path = ensure_clone(root, repo)
            dependencies = corpus_deps.describe(path)
            command = command_with_zig(list(repo.build_command), zig)
            env = os.environ.copy()
            caches = build_cache_roots(root, repo)
            env.setdefault("ZIG_GLOBAL_CACHE_DIR", caches["global"])
            env.setdefault("ZIG_LOCAL_CACHE_DIR", caches["local"])
            cache_roots = {
                "global": portable_path(env["ZIG_GLOBAL_CACHE_DIR"], root),
                "local": portable_path(env["ZIG_LOCAL_CACHE_DIR"], root),
                "packages": portable_path(str(Path(env["ZIG_GLOBAL_CACHE_DIR"]) / "p"), root),
                "shared_package_cache": PACKAGE_CACHE is not None,
            }
            slices = active_slices(repo)
            if slices:
                # Build only what the slices select, one directory at a time.
                hooks = corpus_slices.Hooks(
                    classify=classify_failure,
                    diagnose=corpus_deps.diagnose,
                    describe=corpus_deps.describe,
                    portable=lambda text: portable_text(text, root, repo),
                )
                known_steps = None
                if any(item.mode == "steps" for item in slices):
                    known_steps = corpus_slices.list_steps(command[:2], path, env)
                target_slice = [
                    corpus_slices.build_selection(
                        selection,
                        zig=zig,
                        repo_path=path,
                        env=env,
                        hooks=hooks,
                        expected=selection.slice.expected_classification,
                    )
                    for selection in slice_selections(repo, path, known_steps)
                ]
                failed = [item for item in target_slice if item["returncode"] != 0]
                returncode = int(failed[0]["returncode"]) if failed else 0  # type: ignore[arg-type]
                classification = str(failed[0]["classification"]) if failed else "ok"
                output = "\n".join(corpus_slices.summarize(item) for item in target_slice)[-OUTPUT_TAIL_BYTES:]
                for item in failed:
                    for result_entry in item["results"]:  # type: ignore[union-attr]
                        if result_entry["dependency_diagnosis"] is not None:
                            diagnosis = result_entry["dependency_diagnosis"]
                            break
                    if diagnosis is not None:
                        break
                command = [command[0], "build", "<per target>", "--summary", "all"]
                slice_expected = ",".join(sorted({str(item["expected_classification"]) for item in target_slice}))
                verdicts = [item["matches_expected"] for item in target_slice]
                slice_matches = None if None in verdicts else all(verdicts)
            else:
                result = subprocess.run(
                    command,
                    cwd=path,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                returncode = result.returncode
                # Classify and diagnose on the full text, then store a tail with
                # the clone root replaced, so two clone roots give the same report.
                classification = classify_failure(result.stdout, returncode)
                if returncode != 0:
                    diagnosis = corpus_deps.diagnose(portable_text(result.stdout, root, repo), dependencies, Path("<root>") / repo.name)
                output = portable_text(result.stdout, root, repo)[-OUTPUT_TAIL_BYTES:]
        report.append(
            {
                "name": repo.name,
                "command": [portable_text(part, root, repo) for part in command] if zig else command,
                "zig": repo.build_zig,
                "dependencies": dependencies,
                "dependency_diagnosis": diagnosis,
                "cache_roots": cache_roots,
                "toolchain": resolution.as_dict(),
                "returncode": returncode,
                "classification": classification,
                "expected_classification": slice_expected or repo.expected_build_classification,
                "matches_expected": slice_matches
                if slice_expected
                else expected_matches(classification, repo.expected_build_classification),
                "target_slice": target_slice,
                "selected_target_paths": [path for item in target_slice for path in item["selected_paths"]],  # type: ignore[union-attr]
                "integration_kind": repo.integration_kind,
                "azazel_status": repo.parity_status,
                "first_targets": list(repo.first_targets),
                "system_deps": list(repo.system_deps),
                "required_tools": list(repo.required_tools),
                "pkg_config_libs": list(repo.pkg_config_libs),
                "system_requirements": preflight,
                "replacement_gaps": list(repo.replacement_gaps),
                "next_action": next_action(repo, classification, output),
                "output": output,
            }
        )
        print(
            f"{repo.name}: build {classification} "
            f"(expected {slice_expected or repo.expected_build_classification})"
        )
        for item in target_slice:
            chosen = ", ".join(item["selected_paths"]) or "nothing"  # type: ignore[arg-type]
            print(f"  slice {item['slice']}: {item['classification']} for {chosen}")
            for result_entry in item["results"]:  # type: ignore[union-attr]
                if result_entry["returncode"] != 0:
                    print(f"    {result_entry['path']}: {result_entry['classification']}")
        if not zig:
            print(f"  toolchain: {resolution.diagnostic}")
        elif not preflight["ready"]:
            for line in str(preflight["diagnostic"]).splitlines():
                print(f"  {line}")
        if diagnosis is not None:
            print(f"  {diagnosis['explanation']}")
    (root / "build-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def load_parity_manifest(path: Path, repo: Repo) -> dict[str, object]:
    manifest_path = path / ".azazel" / "parity.json"
    if not manifest_path.exists():
        return {
            "schema": 1,
            "repo": repo.name,
            "baseline": {
                "command": list(repo.baseline_command),
                "expected_classification": repo.expected_classification,
                "preferred_zig": repo.preferred_zig,
            },
            "build": {
                "command": list(repo.build_command),
                "zig": repo.build_zig,
                "toolchain": repo.required_toolchain().manifest(),
                "expected_classification": repo.expected_build_classification,
            },
            "azazel": {
                "command": list(repo.azazel_command),
                "status": repo.parity_status,
                "first_targets": list(repo.first_targets),
                "system_deps": list(repo.system_deps),
                "required_tools": list(repo.required_tools),
                "pkg_config_libs": list(repo.pkg_config_libs),
                "requirements": [item.manifest() for item in repo.requirements],
                "replacement_gaps": list(repo.replacement_gaps),
                "integration_kind": repo.integration_kind,
                "executable_parity": {
                    "status": repo.executable_parity_status,
                    "command": list(repo.executable_parity_command),
                    "expected_classification": repo.expected_executable_parity_classification,
                    "targets": list(repo.executable_parity_targets),
                    "install_checks": list(repo.executable_parity_install_checks),
                    "generated_outputs": list(repo.executable_parity_generated_outputs),
                    "workdir": ".azazel/parity-work",
                },
            },
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    azazel = manifest.setdefault("azazel", {})
    azazel.setdefault(
        "executable_parity",
        {
            "status": repo.executable_parity_status,
            "command": list(repo.executable_parity_command),
            "expected_classification": repo.expected_executable_parity_classification,
            "targets": list(repo.executable_parity_targets),
            "install_checks": list(repo.executable_parity_install_checks),
            "generated_outputs": list(repo.executable_parity_generated_outputs),
            "workdir": ".azazel/parity-work",
        },
    )
    executable = azazel["executable_parity"]
    executable["status"] = repo.executable_parity_status
    executable["command"] = list(repo.executable_parity_command)
    executable["expected_classification"] = repo.expected_executable_parity_classification
    executable["targets"] = list(repo.executable_parity_targets)
    executable["install_checks"] = list(repo.executable_parity_install_checks)
    executable["generated_outputs"] = list(repo.executable_parity_generated_outputs)
    return manifest


def parity(root: Path, repos: list[Repo]) -> None:
    report = []
    for repo in repos:
        path = ensure_clone(root, repo)
        manifest = load_parity_manifest(path, repo)
        baseline = manifest["baseline"]
        azazel = manifest["azazel"]
        command = list(baseline["command"])
        expected = str(baseline["expected_classification"])
        result = run(command, cwd=path, check=False)
        output = result.stdout[-OUTPUT_TAIL_BYTES:]
        classification = classify_failure(output, result.returncode)
        azazel_status = str(azazel.get("status", "unknown"))
        parity_state = "ready" if classification == "ok" and azazel_status == "ready" else "blocked"
        entry = {
            "name": repo.name,
            "baseline": {
                "command": command,
                "returncode": result.returncode,
                "classification": classification,
                "expected_classification": expected,
                "matches_expected": expected_matches(classification, expected),
                "output": output,
            },
            "azazel": {
                "command": list(azazel["command"]),
                "status": azazel_status,
                "first_targets": list(azazel.get("first_targets", [])),
                "system_deps": list(azazel.get("system_deps", [])),
                "required_tools": list(azazel.get("required_tools", [])),
                "pkg_config_libs": list(azazel.get("pkg_config_libs", [])),
                "replacement_gaps": list(azazel.get("replacement_gaps", [])),
                "executable_parity": dict(azazel.get("executable_parity", {})),
            },
            "parity": parity_state,
        }
        # The directories the declared slices select, with their package-local
        # roots. A parity run records them next to the baseline it measured.
        selections = slice_selections(repo, path)
        entry["target_slices"] = [selection.manifest() for selection in selections]
        entry["selected_target_paths"] = selected_paths(selections)
        if repo.executable_parity_generated_outputs:
            # A slice that declares generated outputs is validated here: it is
            # built, and each declared file must exist afterwards.
            slice_entry = executable_parity_entry(root, repo, path)
            entry["generated_outputs"] = {
                "declared": slice_entry["generated_outputs"],
                "validated": slice_entry["generated_outputs_validated"],
                "missing": slice_entry["missing_generated_outputs"],
                "classification": slice_entry["classification"],
                "expected_classification": slice_entry["expected_classification"],
                "command": slice_entry["command"],
                "output": slice_entry["output"],
            }
        report.append(entry)
        print(
            f"{repo.name}: baseline {classification} "
            f"(expected {expected}) -> parity {parity_state}"
        )
        for selection in selections:
            chosen = ", ".join(target.path for target in selection.selected) or "nothing"
            print(f"  target slice {selection.slice.name}: {chosen}")
        if "generated_outputs" in entry:
            generated = entry["generated_outputs"]
            state = "validated" if generated["validated"] else f"not validated ({generated['classification']})"
            print(f"  generated outputs {state}: {', '.join(generated['declared'])}")
    (root / "parity-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def executable_parity_entry(root: Path, repo: Repo, path: Path) -> dict[str, object]:
    """Build one repo's Azazel target slice and check what it must produce."""
    write_executable_parity_workspace(path, repo)
    materialize_executable_parity_deps(path, repo)
    manifest = load_parity_manifest(path, repo)
    azazel = manifest["azazel"]
    executable = dict(azazel.get("executable_parity", {}))
    status = str(executable.get("status", "not-modeled"))
    expected = str(executable.get("expected_classification", "not-modeled"))
    targets = list(executable.get("targets", []))
    command = list(executable.get("command", []))
    install_checks = list(executable.get("install_checks", []))
    generated_outputs = list(executable.get("generated_outputs", []))
    missing_generated: list[str] = []
    workdir = path / str(executable.get("workdir", ".azazel/parity-work"))

    if status != "ready":
        classification = "not-modeled"
        returncode = 0
        output = f"no executable Azazel parity target is modeled for {repo.name}"
    elif not workdir.exists():
        classification = "missing-parity-workspace"
        returncode = 127
        output = f"missing Azazel parity workspace: {workdir}"
    else:
        gen = run(["./gen_build_spec.sh"], cwd=workdir, check=False)
        if gen.returncode != 0:
            classification = classify_failure(gen.stdout, gen.returncode)
            returncode = gen.returncode
            output = gen.stdout[-OUTPUT_TAIL_BYTES:]
        else:
            resolution = resolve_toolchain(repo)
            zig = resolution.path
            if not zig:
                classification = resolution.status
                returncode = 127
                output = resolution.diagnostic
            else:
                # Remove stale results so a check cannot pass on an old file.
                for check in install_checks + generated_outputs:
                    stale = workdir / check
                    if stale.is_file():
                        stale.unlink()
                resolved_command = command_with_zig(command, zig)
                env = os.environ.copy()
                safe_name = repo.name.replace("-", "_")
                env.setdefault("ZIG_GLOBAL_CACHE_DIR", str(root / f".zig-cache-exec-{safe_name}-{repo.build_zig}"))
                env.setdefault("ZIG_LOCAL_CACHE_DIR", str(root / f".zig-cache-local-exec-{safe_name}-{repo.build_zig}"))
                result = subprocess.run(
                    resolved_command,
                    cwd=workdir,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                classification = classify_failure(result.stdout, result.returncode)
                returncode = result.returncode
                output = (gen.stdout + result.stdout)[-OUTPUT_TAIL_BYTES:]
                command = resolved_command
                if returncode == 0 and install_checks:
                    missing = [check for check in install_checks if not (workdir / check).exists()]
                    if missing:
                        classification = "missing-install-artifact"
                        returncode = 1
                        output = (
                            output
                            + "\nmissing executable parity install checks:\n"
                            + "\n".join(missing)
                        )[-OUTPUT_TAIL_BYTES:]
                if returncode == 0 and generated_outputs:
                    missing_generated = [
                        check
                        for check in generated_outputs
                        if not (workdir / check).is_file() or (workdir / check).stat().st_size == 0
                    ]
                    if missing_generated:
                        classification = "missing-generated-output"
                        returncode = 1
                        output = (
                            output
                            + "\nmissing or empty generated outputs:\n"
                            + "\n".join(missing_generated)
                        )[-OUTPUT_TAIL_BYTES:]

    return {
        "name": repo.name,
        "status": status,
        "targets": targets,
        "install_checks": install_checks,
        "generated_outputs": generated_outputs,
        "generated_outputs_validated": bool(generated_outputs) and returncode == 0 and not missing_generated,
        "missing_generated_outputs": missing_generated,
        "workdir": str(workdir.relative_to(path)) if workdir.is_relative_to(path) else str(workdir),
        "command": command,
        "zig": repo.build_zig,
        "returncode": returncode,
        "classification": classification,
        "expected_classification": expected,
        "matches_expected": classification == expected,
        "output": output,
    }


def executable_parity(root: Path, repos: list[Repo]) -> None:
    report = []
    for repo in repos:
        path = ensure_clone(root, repo)
        entry = executable_parity_entry(root, repo, path)
        report.append(entry)
        print(f"{repo.name}: executable parity {entry['classification']} (expected {entry['expected_classification']})")
    (root / "executable-parity-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def classify_failure(output: str, returncode: int) -> str:
    if returncode == 0:
        return "ok"
    if "Required Zig version 2026.4.10-mach" in output:
        return "custom-zig-toolchain"
    if "wayland-scanner" in output or "pkg-config --variable" in output:
        return "system-dependency"
    if "GitLfsContentTokenNotFound" in output or "GitLfsContentCheckFailed" in output:
        return "missing-lfs-content"
    if "name must be a valid bare zig identifier" in output:
        return "dependency-format"
    # A located build.zig.zon error names its own cause. Read it before the
    # broader text matches below, which can also appear in a source line Zig
    # echoes under the error.
    manifest_error = corpus_deps.classify(
        "\n".join(match.group(0) for match in corpus_deps._ZON_ERROR.finditer(output))
    )
    if manifest_error is not None:
        return manifest_error[0]
    if (
        "unsupported Zig version" in output
        or "unsupported zig version" in output
        or "minimum_zig_version" in output
        or "not yet supported by ZLS" in output
        or "@import' of ZON" in output
        or "invalid builtin function: '@Struct'" in output
        or "expected ')', found '.'" in output
    ):
        return "zig-toolchain"
    if (
        "unable to discover remote git server capabilities" in output
        or "Could not resolve host" in output
        or "invalid HTTP response" in output
    ):
        return "dependency-fetch"
    if "failed to create temporary zip file" in output:
        return "dependency-fetch"
    if "bad HTTP response code" in output or "unable to connect to server" in output:
        return "dependency-fetch"
    if "unable to open" in output and "zig-pkg" in output:
        return "dependency-fetch"
    if "xcodebuild transitive failure" in output or "copy app bundle transitive failure" in output:
        return "platform-package"
    if "no field named" in output or "member function expected" in output or "has no member named" in output:
        return "zig-api-drift"
    if "invalid format string" in output:
        return "zig-api-drift"
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.environ.get("AZAZEL_HUGE_ROOT", "/tmp/azazel-huge-forks"))
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--roadmap", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--parity", action="store_true")
    parser.add_argument("--executable-parity", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument(
        "--dependencies",
        action="store_true",
        help="write each repo's build.zig.zon dependency metadata to dependencies-results.json",
    )
    parser.add_argument(
        "--package-cache",
        default=os.environ.get("AZAZEL_PACKAGE_CACHE"),
        help="a Zig global cache directory shared by every --build, so fetched packages survive a fresh --root",
    )
    parser.add_argument("--push", action="store_true")
    parser.add_argument(
        "--slice",
        action="append",
        default=[],
        dest="slices",
        help="build only the named target slice of a repo; repeatable. Without it, every declared slice is built",
    )
    parser.add_argument(
        "--target-path",
        action="append",
        default=[],
        help="narrow the selected slices to directories matching this glob, such as 'samples/minimal_glfw_*'; repeatable",
    )
    parser.add_argument(
        "--whole-repo",
        action="store_true",
        help="run the repo's full build command and ignore its target slices",
    )
    parser.add_argument(
        "--fetch-toolchains",
        action="store_true",
        help="download a required Zig toolchain that is not installed, from its index or a known mirror",
    )
    parser.add_argument(
        "--refresh-base",
        action="store_true",
        help="recreate the integration branch from origin/main before writing the .azazel overlay",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="limit prepare/audit/parity/executable-parity/build/doctor to a repo name, upstream owner/name, or fork owner/name; repeatable",
    )
    parser.add_argument(
        "--expect-count",
        type=int,
        default=None,
        help="fail if the selected corpus size is not this count; useful before 10-repo batch runs",
    )
    args = parser.parse_args()

    global FETCH_TOOLCHAINS, PACKAGE_CACHE, REQUESTED_SLICES, NARROW_PATHS, WHOLE_REPO
    REQUESTED_SLICES = tuple(args.slices)
    NARROW_PATHS = tuple(args.target_path)
    WHOLE_REPO = args.whole_repo
    FETCH_TOOLCHAINS = args.fetch_toolchains
    PACKAGE_CACHE = Path(args.package_cache).resolve() if args.package_cache else None

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    repos = select_repos(args.repo)
    if args.expect_count is not None and len(repos) != args.expect_count:
        raise SystemExit(f"expected {args.expect_count} repos, found {len(repos)}")

    declared = {item.name for repo in repos for item in repo.target_slices}
    unknown = sorted(set(REQUESTED_SLICES) - declared)
    if unknown:
        known = ", ".join(sorted(declared)) or "none declared by the selected repos"
        raise SystemExit(f"unknown target slice(s): {', '.join(unknown)}\nslices declared by the selected repos: {known}")

    if args.plan:
        plan(root, repos, args.expect_count)
    if args.roadmap:
        roadmap(root, repos, args.expect_count)
    if args.prepare:
        prepare(root, repos, args.push, args.refresh_base)
    if args.audit:
        audit(root, repos)
    if args.parity:
        parity(root, repos)
    if args.executable_parity:
        executable_parity(root, repos)
    if args.build:
        run_build(root, repos)
    if args.doctor:
        doctor(root, repos)
    if args.dependencies:
        dependencies_report(root, repos)
    if (
        not args.prepare
        and not args.plan
        and not args.roadmap
        and not args.audit
        and not args.parity
        and not args.executable_parity
        and not args.build
        and not args.doctor
        and not args.dependencies
    ):
        parser.error(
            "choose --plan, --roadmap, --prepare, --audit, --parity, --executable-parity, --build, --doctor, "
            "and/or --dependencies"
        )


if __name__ == "__main__":
    main()
