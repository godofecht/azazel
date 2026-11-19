"""Build a corpus repo's target slices one directory at a time.

`workspace.resolve_slice` says which directories a slice selects. This module
runs the build for each of them and keeps every result scoped to the directory
it came from: its own command, working directory, output tail, dependency
diagnosis and expected install outputs. One failing sample does not hide the
others, and a failure names the path that failed.

The runner passes in the pieces it owns (failure classification, dependency
diagnosis, path rewriting), so this module has no dependency on
`huge_corpus.py`.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import workspace

OUTPUT_TAIL_BYTES = 4000

# `zig build -l` prints `  <step>   <description>` for each step.
_STEP_LINE = re.compile(r"^\s{2}(\S+)(?:\s{2,}.*)?$")


def parse_steps(listing: str) -> set[str]:
    """Step names out of `zig build -l` output."""
    steps = set()
    for line in listing.splitlines():
        match = _STEP_LINE.match(line)
        if match:
            steps.add(match.group(1))
    return steps


def list_steps(command: list[str], cwd: Path, env: dict[str, str]) -> set[str] | None:
    """The build steps the repo defines on this platform, or None when it will not configure."""
    result = subprocess.run(
        [*command, "-l"],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        return None
    steps = parse_steps(result.stdout)
    return steps or None


@dataclass(frozen=True)
class Hooks:
    """What the corpus runner supplies."""

    classify: Callable[[str, int], str]
    diagnose: Callable[[str, dict[str, object], Path], dict[str, object] | None]
    describe: Callable[[Path], dict[str, object]]
    portable: Callable[[str], str]


def _safe(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path)


def build_target(
    target: workspace.SliceTarget,
    *,
    zig: str,
    repo_path: Path,
    env: dict[str, str],
    hooks: Hooks,
    command_tail: tuple[str, ...] = ("--summary", "all"),
    isolate_cache: bool = False,
) -> dict[str, object]:
    """Build one selected directory and report only on it."""
    cwd = repo_path / target.root if target.root else repo_path
    command = [zig, "build", *target.command_args, *command_tail]
    run_env = dict(env)
    if isolate_cache and run_env.get("ZIG_LOCAL_CACHE_DIR"):
        run_env["ZIG_LOCAL_CACHE_DIR"] = f"{run_env['ZIG_LOCAL_CACHE_DIR']}-{_safe(target.path)}"
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    classification = hooks.classify(result.stdout, result.returncode)
    prefix = repo_path / target.output_prefix
    found = [out for out in target.outputs if (prefix / out).exists()]
    missing = [out for out in target.outputs if out not in found]
    returncode = result.returncode
    if returncode == 0 and missing:
        classification = "missing-slice-output"
        returncode = 1
    info = hooks.describe(cwd)
    diagnosis = None
    portable_output = hooks.portable(result.stdout)
    if result.returncode != 0:
        diagnosis = hooks.diagnose(portable_output, info, Path("<root>") / repo_path.name / target.root)
    tail = portable_output[-OUTPUT_TAIL_BYTES:]
    if missing and result.returncode == 0:
        tail = (tail + "\nmissing slice outputs under " + target.output_prefix + ":\n" + "\n".join(missing))[-OUTPUT_TAIL_BYTES:]
    return {
        "path": target.path,
        "name": target.name,
        "root": target.root or ".",
        "step": target.step or None,
        "command": [hooks.portable(part) for part in command],
        "cwd": target.root or ".",
        "returncode": returncode,
        "classification": classification,
        "output_prefix": target.output_prefix,
        "outputs": {"expected": list(target.outputs), "found": found, "missing": missing},
        "dependency_diagnosis": diagnosis,
        "output": tail,
    }


def build_selection(
    selection: workspace.SliceSelection,
    *,
    zig: str,
    repo_path: Path,
    env: dict[str, str],
    hooks: Hooks,
    expected: str = "ok",
) -> dict[str, object]:
    """Build every selected directory and summarise the slice."""
    results = [
        build_target(
            target,
            zig=zig,
            repo_path=repo_path,
            env=env,
            hooks=hooks,
            isolate_cache=selection.slice.mode == "package",
        )
        for target in selection.selected
    ]
    failed = [result for result in results if result["returncode"] != 0]
    if not results:
        classification, returncode = "empty-slice", 1
    elif failed:
        classification, returncode = str(failed[0]["classification"]), int(failed[0]["returncode"])  # type: ignore[arg-type]
    else:
        classification, returncode = "ok", 0
    summary = selection.manifest()
    summary.update(
        {
            "results": results,
            "failed_paths": [str(result["path"]) for result in failed],
            "built_paths": [str(result["path"]) for result in results if result["returncode"] == 0],
            "classification": classification,
            "returncode": returncode,
            "expected_classification": expected,
            "matches_expected": None if expected == "unverified" else classification == expected,
        }
    )
    return summary


def summarize(summary: dict[str, object]) -> str:
    """Scoped output text for a slice: each target's tail under its own path."""
    parts = []
    for result in summary["results"]:  # type: ignore[union-attr]
        state = "ok" if result["returncode"] == 0 else result["classification"]
        parts.append(f"## {result['path']} ({state})")
        if result["returncode"] != 0:
            parts.append(str(result["output"]).rstrip())
    if not parts:
        patterns = ", ".join(summary["patterns"])  # type: ignore[arg-type]
        parts.append(f"slice {summary['slice']} selected no directory for patterns: {patterns}")
    return "\n".join(parts)

