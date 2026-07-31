#!/usr/bin/env python3
"""Prepare and audit the huge Zig project corpus.

The runner keeps the corpus reproducible:

* clone or update the godofecht forks
* create an `azazel-zaza-integration` branch
* add a `.azazel/` overlay describing the first integration target
* optionally run baseline `zig build --help`
* emit baseline-vs-Azazel parity readiness reports

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
    integration_kind: str = "azazel"
    parity_status: str = "scaffold-only"

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
            "integration_kind": self.integration_kind,
            "parity_status": self.parity_status,
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
    if current != BRANCH:
        existing = run(["git", "branch", "--list", BRANCH], cwd=path).stdout.strip()
        if existing:
            run(["git", "checkout", BRANCH], cwd=path)
        else:
            remote = run(["git", "fetch", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}"], cwd=path, check=False)
            if remote.returncode == 0:
                run(["git", "checkout", "-b", BRANCH, f"origin/{BRANCH}"], cwd=path)
            else:
                run(["git", "checkout", "-b", BRANCH], cwd=path)


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
                    "integration_kind": repo.integration_kind,
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
                "integration_kind": repo.integration_kind,
            },
        }
    return json.loads(manifest_path.read_text(encoding="utf-8"))


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
            },
            "parity": parity_state,
        }
        report.append(entry)
        print(
            f"{repo.name}: baseline {classification} "
            f"(expected {expected}) -> parity {parity_state}"
        )
    (root / "parity-results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


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
    if "unable to discover remote git server capabilities" in output or "Could not resolve host" in output:
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
    parser.add_argument("--build", action="store_true")
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
        help="limit prepare/audit/parity/build to a repo name, upstream owner/name, or fork owner/name; repeatable",
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
    if args.build:
        run_build(root, repos)
    if not args.prepare and not args.audit and not args.parity and not args.build:
        parser.error("choose --prepare, --audit, --parity, and/or --build")


if __name__ == "__main__":
    main()
