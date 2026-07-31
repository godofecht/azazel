#!/usr/bin/env python3
"""Prepare and audit the huge Zig project corpus.

The runner keeps the corpus reproducible:

* clone or update the godofecht forks
* create an `azazel-zaza-integration` branch
* add a small `.azazel/` overlay describing the first integration target
* optionally run baseline `zig build --help`

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


REPOS = [
    Repo("zls", "zigtools/zls", "godofecht/zls", "language server; generated version data, tests, release steps"),
    Repo("libxev", "mitchellh/libxev", "godofecht/libxev", "library variants, examples, benches, manpage generation"),
    Repo("river", "riverwm/river", "godofecht/river", "Wayland compositor; pkg-config, C sources, generated modules"),
    Repo("mach", "hexops/mach", "godofecht/mach", "game engine; generated bindings, assets, custom Zig lane"),
    Repo("microzig", "ZigEmbeddedGroup/microzig", "godofecht/microzig", "embedded workspace with many nested packages"),
    Repo("libvaxis", "rockorager/libvaxis", "godofecht/libvaxis", "TUI library; example matrix and installable demos"),
    Repo("capy", "capy-ui/capy", "godofecht/capy", "native UI toolkit; exact Zig lane requirement"),
    Repo("zig-gamedev", "zig-gamedev/zig-gamedev", "godofecht/zig-gamedev", "large game-dev monorepo with assets and package deps"),
]


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def repo_dir(root: Path, repo: Repo) -> Path:
    return root / repo.name


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
    (overlay / "corpus.json").write_text(
        json.dumps(
            {
                "name": repo.name,
                "upstream": repo.upstream,
                "fork": repo.fork,
                "branch": BRANCH,
                "notes": repo.notes,
                "status": "integration scaffold",
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
    preferred: "0.15"
}
""",
        encoding="utf-8",
    )


def prepare(root: Path, push: bool) -> None:
    for repo in REPOS:
        path = ensure_clone(root, repo)
        checkout_branch(path)
        write_overlay(path, repo)
        run(["git", "add", ".azazel"], cwd=path)
        status = run(["git", "status", "--short"], cwd=path).stdout.strip()
        if status:
            run(["git", "commit", "-m", "Add Azazel/Zaza integration scaffold"], cwd=path)
        if push:
            run(["git", "push", "-u", "origin", BRANCH], cwd=path)
        print(f"{repo.name}: prepared")


def audit(root: Path) -> None:
    report = []
    for repo in REPOS:
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
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    if args.prepare:
        prepare(root, args.push)
    if args.audit:
        audit(root)
    if not args.prepare and not args.audit:
        parser.error("choose --prepare and/or --audit")


if __name__ == "__main__":
    main()
