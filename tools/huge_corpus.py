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
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


BRANCH = "azazel-zaza-integration"
OUTPUT_TAIL_BYTES = 12000


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
    required_tools: tuple[str, ...] = ()
    pkg_config_libs: tuple[str, ...] = ()
    replacement_gaps: tuple[str, ...] = ()
    integration_kind: str = "azazel"
    parity_status: str = "scaffold-only"
    executable_parity_status: str = "not-modeled"
    executable_parity_command: tuple[str, ...] = ()
    expected_executable_parity_classification: str = "not-modeled"
    executable_parity_targets: tuple[str, ...] = ()
    executable_parity_install_checks: tuple[str, ...] = ()

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
            "build_command": list(self.build_command),
            "expected_build_classification": self.expected_build_classification,
            "azazel_command": list(self.azazel_command),
            "expected_baseline_classification": self.expected_classification,
            "first_targets": list(self.first_targets),
            "system_deps": list(self.system_deps),
            "required_tools": list(self.required_tools),
            "pkg_config_libs": list(self.pkg_config_libs),
            "replacement_gaps": list(self.replacement_gaps),
            "integration_kind": self.integration_kind,
            "parity_status": self.parity_status,
            "executable_parity_status": self.executable_parity_status,
            "executable_parity_command": list(self.executable_parity_command),
            "expected_executable_parity_classification": self.expected_executable_parity_classification,
            "executable_parity_targets": list(self.executable_parity_targets),
            "executable_parity_install_checks": list(self.executable_parity_install_checks),
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
        "zig-toolchain",
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("exe:zls", "tests", "generated version data"),
        replacement_gaps=("exact dev-toolchain window", "package dependencies", "generated version data"),
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
        ("pkg-config", "wayland-scanner"),
        ("wayland-scanner",),
        ("system dependency preflight", "generated protocol modules", "pkg-config link metadata"),
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
        replacement_gaps=("generated Unicode tables", "example matrix target selection", "installable demos"),
        executable_parity_status="ready",
        executable_parity_command=("zig", "build", "--summary", "all"),
        expected_executable_parity_classification="zig-api-drift",
        executable_parity_targets=("module:vaxis", "exe:vaxis_probe", "package:zigimg", "package:uucode"),
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
            "asset:sdl2_demo_content",
        ),
        executable_parity_install_checks=(
            ".azazel-install/bin/sdl2_demo_content/zero.png",
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
        required_tools=("git",),
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
        required_tools=("pkg-config",),
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


def toolchain_root() -> Path:
    return Path(os.environ.get("AZAZEL_TOOLCHAIN_ROOT", Path(__file__).resolve().parents[2] / ".toolchains"))


def zig_for(version: str) -> str:
    env_key = "AZAZEL_ZIG_" + "".join(ch for ch in version.upper() if ch.isalnum())
    if os.environ.get(env_key):
        return os.environ[env_key]

    known = {
        "0.14.1": Path("/Users/abhishekshivakumar/zig/0.14.1/zig"),
        "0.15.2": toolchain_root() / "zig-aarch64-macos-0.15.2" / "zig",
        "0.16.0": toolchain_root() / "zig-aarch64-macos-0.16.0" / "zig",
        "0.17-dev": toolchain_root() / "zig-aarch64-macos-0.17-dev" / "zig",
        "mach-2026.4.10": toolchain_root() / "zig-mach-2026.4.10" / "zig",
    }
    candidate = known.get(version)
    if candidate and candidate.exists():
        return str(candidate)
    if version == "0.17-dev":
        matches = sorted(toolchain_root().glob("zig-aarch64-macos-0.17.0-dev.*/zig"))
        if matches:
            return str(matches[-1])

    named = shutil.which(f"zig-{version}")
    if named:
        return named
    if version == "host":
        return shutil.which("zig") or "zig"
    return ""


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
    (overlay / "corpus.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
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
                    "expected_classification": repo.expected_build_classification,
                },
                "azazel": {
                    "command": list(repo.azazel_command),
                    "status": repo.parity_status,
                    "first_targets": list(repo.first_targets),
                    "system_deps": list(repo.system_deps),
                    "required_tools": list(repo.required_tools),
                    "pkg_config_libs": list(repo.pkg_config_libs),
                    "replacement_gaps": list(repo.replacement_gaps),
                    "integration_kind": repo.integration_kind,
                    "executable_parity": {
                        "status": repo.executable_parity_status,
                        "command": list(repo.executable_parity_command),
                        "expected_classification": repo.expected_executable_parity_classification,
                        "targets": list(repo.executable_parity_targets),
                        "install_checks": list(repo.executable_parity_install_checks),
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
        % cue_preferred_lane(repo),
        encoding="utf-8",
    )
    write_executable_parity_workspace(path, repo)


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
    (workspace / ".gitignore").write_text("build_spec.zig\nzig-cache/\nzig-out/\n", encoding="utf-8")
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
        (workspace / "export.cue").write_text(
            """package build

_modules: {
    "xev": xev
    "xev_probe": xev_probe
}

_toolchain: toolchain
_packages: packages
_options: options

build: modules: {
    for k, v in _modules {
        (k): {
            kind: v.kind
            root: v.root
            deps: v.deps
            link: v.link
            pre: v.pre
            post: v.post
            install_dirs: v.install_dirs
            pkg_imports: v.pkg_imports
            pkg_artifacts: v.pkg_artifacts
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
""",
            encoding="utf-8",
        )
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
        (workspace / "project.cue").write_text(
            """package build

toolchain: zig: {
    lanes: ["0.16"]
    preferred: "0.16"
}

packages: {
    zigimg: {
        path: "../../zig-pkg/zigimg-0.1.0-8_eo2oyaFwBZwJpmqPkCfVXWBrHcqbYwmrp1I6bTD3lI"
    }
    uucode: {
        path: "../../zig-pkg/uucode-0.2.0-ZZjBPlK5VADj7fdoq7G8LIHzD5o6FSkcBXXrRWr4jnrA"
        lazy: true
    }
}

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
        },
    ]
}

vaxis_probe: #Module & {
    kind: "exe"
    root: "src/vaxis_probe.zig"
    deps: ["vaxis"]
    link: "import"
}
""",
            encoding="utf-8",
        )
        write_standard_export(workspace, ("vaxis", "vaxis_probe"))
        write_workspace_zon(
            workspace,
            ".vaxis_azazel_parity",
            {
                "zigimg": "../../zig-pkg/zigimg-0.1.0-8_eo2oyaFwBZwJpmqPkCfVXWBrHcqbYwmrp1I6bTD3lI",
                "uucode": "../../zig-pkg/uucode-0.2.0-ZZjBPlK5VADj7fdoq7G8LIHzD5o6FSkcBXXrRWr4jnrA",
            },
        )
        (src_dir / "vaxis_probe.zig").write_text(
            """const vaxis = @import("vaxis");

pub fn main() void {
    _ = vaxis.Vaxis;
    _ = vaxis.Key;
    _ = vaxis.zigimg.Image;
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
}

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
        backend: "glfw_wgpu"
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
        backend: "glfw_wgpu"
    }]
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
}
""",
            encoding="utf-8",
        )
        return

    raise SystemExit(f"repo {repo.name} declares executable parity but has no workspace writer")


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

build: modules: {
    for k, v in _modules {
        (k): {
            kind: v.kind
            root: v.root
            deps: v.deps
            link: v.link
            pre: v.pre
            post: v.post
            install_dirs: v.install_dirs
            pkg_imports: v.pkg_imports
            pkg_artifacts: v.pkg_artifacts
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
""",
        encoding="utf-8",
    )


def write_workspace_zon(
    workspace: Path,
    package_name: str,
    deps: dict[str, str],
    fingerprint: str = "0x556db0b97b71fd4c",
) -> None:
    lines = [
        ".{",
        f"    .name = {package_name},",
        '    .version = "0.0.0",',
        f"    .fingerprint = {fingerprint},",
        "    .dependencies = .{",
    ]
    for name, path in deps.items():
        lines.extend(
            [
                f"        .{name} = .{{",
                f'            .path = "{path}",',
                "        },",
            ]
        )
    lines.extend(
        [
            "    },",
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
        return

    if repo.name != "libvaxis":
        return
    pkg_root = path / "zig-pkg"
    ensure_git_package(
        pkg_root / "zigimg-0.1.0-8_eo2oyaFwBZwJpmqPkCfVXWBrHcqbYwmrp1I6bTD3lI",
        "https://github.com/zigimg/zigimg.git",
        "d695acd97c02e57bb151e8f659d1280f5cd6ca70",
    )
    ensure_git_package(
        pkg_root / "uucode-0.2.0-ZZjBPlK5VADj7fdoq7G8LIHzD5o6FSkcBXXrRWr4jnrA",
        "https://github.com/jacobsandlund/uucode.git",
        "2826a37a4562284fdacd8fa029d49509cc9bffcd",
    )


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


def pkg_config_available(name: str) -> bool:
    if not shutil.which("pkg-config"):
        return False
    return subprocess.run(
        ["pkg-config", "--exists", name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).returncode == 0


def doctor_entry(repo: Repo) -> dict[str, object]:
    zig = zig_for(repo.build_zig)
    tools = [
        {
            "name": tool,
            "path": shutil.which(tool) or "",
            "found": shutil.which(tool) is not None,
        }
        for tool in repo.required_tools
    ]
    pkg_config = [
        {
            "name": lib,
            "found": pkg_config_available(lib),
        }
        for lib in repo.pkg_config_libs
    ]
    ready = bool(zig) and all(tool["found"] for tool in tools) and all(lib["found"] for lib in pkg_config)
    missing = []
    if not zig:
        missing.append(f"zig:{repo.build_zig}")
    missing.extend(f"tool:{tool['name']}" for tool in tools if not tool["found"])
    missing.extend(f"pkg-config:{lib['name']}" for lib in pkg_config if not lib["found"])
    return {
        "name": repo.name,
        "ready": ready,
        "missing": missing,
        "toolchain": {
            "version": repo.build_zig,
            "path": zig,
            "found": bool(zig),
        },
        "required_tools": tools,
        "pkg_config_libs": pkg_config,
        "system_deps": list(repo.system_deps),
        "first_targets": list(repo.first_targets),
        "replacement_gaps": list(repo.replacement_gaps),
        "next_action": next_action(
            repo,
            repo.expected_build_classification if ready else "doctor-blocked",
            "",
        ),
    }


def doctor(root: Path, repos: list[Repo]) -> None:
    report = [doctor_entry(repo) for repo in repos]
    for entry in report:
        status = "ready" if entry["ready"] else "blocked"
        missing = ", ".join(entry["missing"]) if entry["missing"] else "none"
        print(f"{entry['name']}: doctor {status}; missing: {missing}")
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
    if classification == "missing-toolchain":
        return f"install {repo.build_zig} or set AZAZEL_ZIG_{''.join(ch for ch in repo.build_zig.upper() if ch.isalnum())}"
    if classification == "system-dependency":
        deps = ", ".join(repo.system_deps or repo.required_tools)
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


def run_build(root: Path, repos: list[Repo]) -> None:
    report = []
    for repo in repos:
        path = ensure_clone(root, repo)
        zig = zig_for(repo.build_zig)
        if not zig:
            classification = "missing-toolchain"
            output = f"no Zig binary found for {repo.build_zig}"
            returncode = 127
            command = list(repo.build_command)
        else:
            command = command_with_zig(list(repo.build_command), zig)
            env = os.environ.copy()
            safe_name = repo.name.replace("-", "_")
            env.setdefault("ZIG_GLOBAL_CACHE_DIR", str(root / f".zig-cache-{safe_name}-{repo.build_zig}"))
            env.setdefault("ZIG_LOCAL_CACHE_DIR", str(root / f".zig-cache-local-{safe_name}-{repo.build_zig}"))
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
            output = result.stdout[-OUTPUT_TAIL_BYTES:]
            classification = classify_failure(output, returncode)
        report.append(
            {
                "name": repo.name,
                "command": command,
                "zig": repo.build_zig,
                "returncode": returncode,
                "classification": classification,
                "expected_classification": repo.expected_build_classification,
                "matches_expected": expected_matches(classification, repo.expected_build_classification),
                "integration_kind": repo.integration_kind,
                "azazel_status": repo.parity_status,
                "first_targets": list(repo.first_targets),
                "system_deps": list(repo.system_deps),
                "required_tools": list(repo.required_tools),
                "pkg_config_libs": list(repo.pkg_config_libs),
                "replacement_gaps": list(repo.replacement_gaps),
                "next_action": next_action(repo, classification, output),
                "output": output,
            }
        )
        print(
            f"{repo.name}: build {classification} "
            f"(expected {repo.expected_build_classification})"
        )
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
                "expected_classification": repo.expected_build_classification,
            },
            "azazel": {
                "command": list(repo.azazel_command),
                "status": repo.parity_status,
                "first_targets": list(repo.first_targets),
                "system_deps": list(repo.system_deps),
                "required_tools": list(repo.required_tools),
                "pkg_config_libs": list(repo.pkg_config_libs),
                "replacement_gaps": list(repo.replacement_gaps),
                "integration_kind": repo.integration_kind,
                "executable_parity": {
                    "status": repo.executable_parity_status,
                    "command": list(repo.executable_parity_command),
                    "expected_classification": repo.expected_executable_parity_classification,
                    "targets": list(repo.executable_parity_targets),
                    "install_checks": list(repo.executable_parity_install_checks),
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
            "workdir": ".azazel/parity-work",
        },
    )
    executable = azazel["executable_parity"]
    executable["status"] = repo.executable_parity_status
    executable["command"] = list(repo.executable_parity_command)
    executable["expected_classification"] = repo.expected_executable_parity_classification
    executable["targets"] = list(repo.executable_parity_targets)
    executable["install_checks"] = list(repo.executable_parity_install_checks)
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
        report.append(entry)
        print(
            f"{repo.name}: baseline {classification} "
            f"(expected {expected}) -> parity {parity_state}"
        )
    (root / "parity-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def executable_parity(root: Path, repos: list[Repo]) -> None:
    report = []
    for repo in repos:
        path = ensure_clone(root, repo)
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
                zig = zig_for(repo.build_zig)
                if not zig:
                    classification = "missing-toolchain"
                    returncode = 127
                    output = f"no Zig binary found for {repo.build_zig}"
                else:
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

        matches = classification == expected
        report.append(
            {
                "name": repo.name,
                "status": status,
                "targets": targets,
                "install_checks": install_checks,
                "workdir": str(workdir.relative_to(path)) if workdir.is_relative_to(path) else str(workdir),
                "command": command,
                "zig": repo.build_zig,
                "returncode": returncode,
                "classification": classification,
                "expected_classification": expected,
                "matches_expected": matches,
                "output": output,
            }
        )
        print(f"{repo.name}: executable parity {classification} (expected {expected})")
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
    parser.add_argument("--push", action="store_true")
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

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    repos = select_repos(args.repo)
    if args.expect_count is not None and len(repos) != args.expect_count:
        raise SystemExit(f"expected {args.expect_count} repos, found {len(repos)}")

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
    if (
        not args.prepare
        and not args.plan
        and not args.roadmap
        and not args.audit
        and not args.parity
        and not args.executable_parity
        and not args.build
        and not args.doctor
    ):
        parser.error("choose --plan, --roadmap, --prepare, --audit, --parity, --executable-parity, --build, and/or --doctor")


if __name__ == "__main__":
    main()
