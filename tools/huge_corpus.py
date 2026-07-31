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
    azazel_command: tuple[str, ...]
    expected_classification: str
    first_targets: tuple[str, ...]
    system_deps: tuple[str, ...] = ()
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
            "azazel_command": list(self.azazel_command),
            "expected_baseline_classification": self.expected_classification,
            "first_targets": list(self.first_targets),
            "system_deps": list(self.system_deps),
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
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("exe:zls", "tests", "generated version data"),
    ),
    Repo(
        "libxev",
        "mitchellh/libxev",
        "godofecht/libxev",
        "library variants, examples, benches, manpage generation",
        "0.15",
        ("zig", "build", "--help"),
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-api-drift",
        ("lib:xev", "examples", "benchmarks", "manpage generation"),
    ),
    Repo(
        "river",
        "riverwm/river",
        "godofecht/river",
        "Wayland compositor; pkg-config, C sources, generated modules",
        "0.15",
        ("zig", "build", "--help"),
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
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("module:mach", "examples", "generated Vulkan bindings", "asset steps"),
    ),
    Repo(
        "microzig",
        "ZigEmbeddedGroup/microzig",
        "godofecht/microzig",
        "embedded workspace with many nested packages",
        "0.15",
        ("zig", "build", "--help"),
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-toolchain",
        ("workspace packages", "board ports", "nested build packages", "tools"),
    ),
    Repo(
        "libvaxis",
        "rockorager/libvaxis",
        "godofecht/libvaxis",
        "TUI library; example matrix and installable demos",
        "0.15",
        ("zig", "build", "--help"),
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
        ("azazel", "parity", "--manifest", ".azazel/parity.json"),
        "zig-api-drift",
        ("package modules", "asset-heavy examples", "optional dependency selection"),
    ),
]


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def repo_dir(root: Path, repo: Repo) -> Path:
    return root / repo.name


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
            run(["git", "checkout", "-b", BRANCH], cwd=path)


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
                "azazel": {
                    "command": list(repo.azazel_command),
                    "status": repo.parity_status,
                    "first_targets": list(repo.first_targets),
                    "system_deps": list(repo.system_deps),
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


def prepare(root: Path, repos: list[Repo], push: bool) -> None:
    for repo in repos:
        path = ensure_clone(root, repo)
        checkout_branch(path)
        write_overlay(path, repo)
        run(["git", "add", ".azazel"], cwd=path)
        staged = run(["git", "diff", "--cached", "--quiet"], cwd=path, check=False)
        if staged.returncode:
            run(["git", "commit", "-m", "Add Azazel/Zaza integration scaffold"], cwd=path)
        if push:
            run(["git", "push", "-u", "origin", BRANCH], cwd=path)
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
            "azazel": {
                "command": list(repo.azazel_command),
                "status": repo.parity_status,
                "first_targets": list(repo.first_targets),
                "system_deps": list(repo.system_deps),
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
    if (
        "unsupported Zig version" in output
        or "minimum_zig_version" in output
        or "@import' of ZON" in output
        or "invalid builtin function: '@Struct'" in output
        or "expected ')', found '.'" in output
    ):
        return "zig-toolchain"
    if "unable to discover remote git server capabilities" in output or "Could not resolve host" in output:
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
    parser.add_argument("--push", action="store_true")
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="limit prepare/audit/parity to a repo name, upstream owner/name, or fork owner/name; repeatable",
    )
    args = parser.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    repos = select_repos(args.repo)

    if args.prepare:
        prepare(root, repos, args.push)
    if args.audit:
        audit(root, repos)
    if args.parity:
        parity(root, repos)
    if not args.prepare and not args.audit and not args.parity:
        parser.error("choose --prepare, --audit, and/or --parity")


if __name__ == "__main__":
    main()
