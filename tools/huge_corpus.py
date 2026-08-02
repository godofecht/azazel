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
        expected_executable_parity_classification="ok",
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


def refresh_branch_base(path: Path) -> None:
    run(["git", "fetch", "origin", "main"], cwd=path)
    run(["git", "checkout", "-B", BRANCH, "origin/main"], cwd=path)


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
            pkg_imports: v.pkg_imports
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
            pkg_imports: v.pkg_imports
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


def write_workspace_zon(workspace: Path, package_name: str, deps: dict[str, str]) -> None:
    lines = [
        ".{",
        f"    .name = {package_name},",
        '    .version = "0.0.0",',
        "    .fingerprint = 0x556db0b97b71fd4c,",
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
            if refresh_base:
                run(["git", "fetch", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}"], cwd=path, check=False)
                lease = run(["git", "rev-parse", f"origin/{BRANCH}"], cwd=path, check=False).stdout.strip()
                if lease:
                    push_cmd = ["git", "push", "-u", f"--force-with-lease={BRANCH}:{lease}", "origin", BRANCH]
                else:
                    push_cmd = ["git", "push", "-u", "origin", BRANCH]
            else:
                push_cmd = ["git", "push", "-u", "origin", BRANCH]
            run(push_cmd, cwd=path)
        print(f"{repo.name}: prepared")


def audit(root: Path, repos: list[Repo]) -> None:
    report = []
    for repo in repos:
        path = ensure_clone(root, repo)
        result = run(["zig", "build", "--help"], cwd=path, check=False)
        output = result.stdout[-4000:]
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
            output = result.stdout[-4000:]
            classification = classify_failure(output, returncode)
        report.append(
            {
                "name": repo.name,
                "command": command,
                "zig": repo.build_zig,
                "returncode": returncode,
                "classification": classification,
                "expected_classification": repo.expected_build_classification,
                "matches_expected": classification == repo.expected_build_classification,
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
            "workdir": ".azazel/parity-work",
        },
    )
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
        output = result.stdout[-4000:]
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
                "matches_expected": classification == expected,
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
        manifest = load_parity_manifest(path, repo)
        azazel = manifest["azazel"]
        executable = dict(azazel.get("executable_parity", {}))
        status = str(executable.get("status", "not-modeled"))
        expected = str(executable.get("expected_classification", "not-modeled"))
        targets = list(executable.get("targets", []))
        command = list(executable.get("command", []))
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
                output = gen.stdout[-4000:]
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
                    output = (gen.stdout + result.stdout)[-4000:]
                    command = resolved_command

        matches = classification == expected
        report.append(
            {
                "name": repo.name,
                "status": status,
                "targets": targets,
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
    if "no field named" in output or "member function expected" in output or "has no member named" in output:
        return "zig-api-drift"
    if "invalid format string" in output:
        return "zig-api-drift"
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.environ.get("AZAZEL_HUGE_ROOT", "/tmp/azazel-huge-forks"))
    parser.add_argument("--prepare", action="store_true")
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
    args = parser.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    repos = select_repos(args.repo)

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
        and not args.audit
        and not args.parity
        and not args.executable_parity
        and not args.build
        and not args.doctor
    ):
        parser.error("choose --prepare, --audit, --parity, --executable-parity, --build, and/or --doctor")


if __name__ == "__main__":
    main()
