"""Nested workspaces and target slices.

Two parts share one glob matcher.

Azazel core. A project declares `subprojects` in project.cue. Each is a nested
package with a package-local root and an output directory, and each module can
name the subproject it belongs to. `Target` is one module as a build can select
it, and `select` applies `--slice` globs and `--subproject` names the way
`build.zig` does.

Corpus. A repo can declare `TargetSlice` values. A slice names a group of
nested packages or sample directories by glob, such as `samples/minimal_*` or
`port/*/*`, and says how to build each one alone. `resolve_slice` finds the
matching directories in a clone, so a corpus run builds the slice and not the
whole repo.

Glob rules, shared with `compat.zig` through `tools/glob_cases.txt`:

  `*`    any run of characters except `/`
  `?`    one character except `/`
  `**`   any run of characters including `/`; `**/` also matches no segment
  other  matches itself
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import zon


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**", i):
                i += 2
                if pattern.startswith("/", i):
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def glob_match(pattern: str, text: str) -> bool:
    return _glob_regex(pattern).fullmatch(text) is not None


# --- Azazel core -------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One module as a build can select it."""

    name: str
    kind: str
    subproject: str
    subproject_path: str
    output_dir: str
    root: str
    link: str = "abi"

    @property
    def target_path(self) -> str:
        return posixpath.join(self.subproject_path, self.name) if self.subproject_path else self.name

    @property
    def install_dir(self) -> str:
        """Install location relative to the prefix, matching build.zig."""
        # A module, and a static library merged into its dependents, installs nothing.
        if self.kind == "module" or (self.kind == "static" and self.link == "import"):
            return ""
        leaf = "bin" if self.kind == "exe" else "lib"
        return posixpath.join(self.output_dir, leaf) if self.output_dir else leaf

    def manifest(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "target_path": self.target_path,
            "subproject": self.subproject or None,
            "subproject_path": self.subproject_path or None,
            "root": self.root,
            "install_dir": self.install_dir or None,
        }


def module_targets(data: dict) -> list[Target]:
    """Every module of an exported build, with its subproject resolved."""
    subprojects = data.get("subprojects") or {}
    targets = []
    for name, module in (data.get("modules") or {}).items():
        owner = module.get("subproject") or ""
        sub = subprojects.get(owner) or {}
        targets.append(
            Target(
                name=name,
                kind=module.get("kind", ""),
                subproject=owner,
                subproject_path=sub.get("path", "") if owner else "",
                output_dir=sub.get("output_dir", "") if owner else "",
                root=module.get("root", ""),
                link=module.get("link", "abi"),
            )
        )
    return targets


def selects(target: Target, slices: tuple[str, ...] = (), subprojects: tuple[str, ...] = ()) -> bool:
    """The rule `build.zig` applies. No selection selects everything."""
    if not slices and not subprojects:
        return True
    if target.subproject and target.subproject in subprojects:
        return True
    for pattern in slices:
        if glob_match(pattern, target.target_path):
            return True
        if target.subproject_path and glob_match(pattern, target.subproject_path):
            return True
    return False


def select(targets: list[Target], slices: tuple[str, ...] = (), subprojects: tuple[str, ...] = ()) -> list[Target]:
    return [target for target in targets if selects(target, slices, subprojects)]


def selection_errors(
    data: dict, slices: tuple[str, ...] = (), subprojects: tuple[str, ...] = ()
) -> list[str]:
    """Problems with a requested selection, before the build starts."""
    errors = []
    declared = data.get("subprojects") or {}
    targets = module_targets(data)
    for name in subprojects:
        if name not in declared:
            known = ", ".join(sorted(declared)) or "none declared"
            errors.append(f"subproject {name!r} is not declared in project.cue (declared: {known})")
    for pattern in slices:
        if not select(targets, (pattern,), ()):
            paths = ", ".join(target.target_path for target in targets)
            errors.append(f"slice {pattern!r} matches no module or subproject path (target paths: {paths})")
    return errors


def _bad_relative(value: str) -> bool:
    return (
        value.startswith("/")
        or value.endswith("/")
        or posixpath.normpath(value) != value
        or ".." in value.split("/")
    )


def subproject_errors(data: dict, root: Path) -> list[str]:
    """Check subprojects and the modules assigned to them.

    Every message names the subproject it concerns, so a failure in one nested
    package is not reported against the whole repository.
    """
    errors: list[str] = []
    subprojects = data.get("subprojects") or {}
    if not isinstance(subprojects, dict):
        return ["build.subprojects did not export as an object"]
    owners: dict[str, str] = {}
    for name, sub in subprojects.items():
        path = sub.get("path", "")
        where = f"subproject {name!r} ({path})"
        if not path or _bad_relative(path):
            errors.append(f"{where}: path must be a normalized relative path with no .. segment")
            continue
        if not (root / path).is_dir():
            errors.append(f"{where}: directory does not exist")
        if path in owners:
            errors.append(f"{where}: same path as subproject {owners[path]!r}")
        owners[path] = name
        output_dir = sub.get("output_dir", "")
        if output_dir and _bad_relative(output_dir):
            errors.append(f"{where}: output_dir must be a normalized relative path with no .. segment")
    for module_name, module in (data.get("modules") or {}).items():
        owner = module.get("subproject") or ""
        if not owner:
            continue
        if owner not in subprojects:
            errors.append(f"module {module_name!r} belongs to subproject {owner!r}, which is not declared")
            continue
        path = subprojects[owner].get("path", "")
        source = module.get("root", "")
        if path and not source.startswith(path + "/"):
            errors.append(f"subproject {owner!r} ({path}): module {module_name!r} root {source} lies outside it")
    return errors


def nesting(subprojects: dict[str, dict]) -> dict[str, str]:
    """Map each subproject to the subproject that contains it, when one does."""
    parents: dict[str, str] = {}
    for name, sub in subprojects.items():
        best = ""
        for other, candidate in subprojects.items():
            if other == name:
                continue
            base = candidate.get("path", "")
            if base and sub.get("path", "").startswith(base + "/") and len(base) > len(subprojects.get(best, {}).get("path", "")):
                best = other
        if best:
            parents[name] = best
    return parents


# --- Corpus ------------------------------------------------------------------

# Directories that hold build output or history, never a package to build.
SKIPPED_DIRS = frozenset({".git", ".zig-cache", "zig-cache", "zig-out", "zig-pkg", "node_modules", ".azazel", ".hg", ".svn"})
MAX_PACKAGES = 5000


@dataclass(frozen=True)
class NestedPackage:
    """A directory inside a repo that builds on its own."""

    path: str
    has_build_zig: bool
    has_manifest: bool
    name: str = ""
    version: str = ""
    minimum_zig_version: str = ""
    parent: str = ""

    def manifest(self) -> dict[str, object]:
        return {
            "path": self.path,
            "has_build_zig": self.has_build_zig,
            "has_manifest": self.has_manifest,
            "name": self.name or None,
            "version": self.version or None,
            "minimum_zig_version": self.minimum_zig_version or None,
            "parent": self.parent or None,
        }


def discover_packages(repo: Path) -> list[NestedPackage]:
    """Find every nested directory with a `build.zig` or a `build.zig.zon`.

    The repo root is not listed. `parent` is the nearest enclosing package, or
    empty when the enclosing package is the repo root.
    """
    repo = repo.resolve()
    found: dict[str, tuple[bool, bool]] = {}
    stack = [repo]
    while stack and len(found) < MAX_PACKAGES:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        names = {entry.name for entry in entries}
        if directory != repo and ("build.zig" in names or "build.zig.zon" in names):
            found[directory.relative_to(repo).as_posix()] = ("build.zig" in names, "build.zig.zon" in names)
        for entry in entries:
            if entry.name in SKIPPED_DIRS or entry.is_symlink() or not entry.is_dir():
                continue
            stack.append(entry)

    packages = []
    for path in sorted(found):
        has_build, has_manifest = found[path]
        name = version = minimum = ""
        if has_manifest:
            try:
                parsed = zon.parse((repo / path / "build.zig.zon").read_text(encoding="utf-8", errors="replace"))
            except (zon.ZonError, ValueError, OSError):
                parsed = None
            if isinstance(parsed, dict):
                name = str(parsed.get("name", ""))
                version = str(parsed.get("version", ""))
                minimum = str(parsed.get("minimum_zig_version", ""))
        parent = ""
        for other in found:
            if path.startswith(other + "/") and len(other) > len(parent):
                parent = other
        packages.append(NestedPackage(path, has_build, has_manifest, name, version, minimum, parent))
    return packages


@dataclass(frozen=True)
class TargetSlice:
    """A group of nested packages or sample directories, built one at a time.

    patterns   globs over package-root paths relative to the repo, such as
               `samples/minimal_*` or `port/*/*`
    mode       `package` runs the build inside each matching package root.
               `steps` runs it at the repo root, once per matching directory,
               with the directory's name as the build step.
    args       arguments added after `zig build` for every target
    outputs    paths expected under the install prefix after a target builds.
               `{name}` is the target's directory name.
    """

    name: str
    patterns: tuple[str, ...]
    mode: str = "package"
    args: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    description: str = ""
    # The classification a slice build is expected to give. "unverified" skips
    # the comparison until the slice has been run against the real repo.
    expected_classification: str = "ok"

    def __post_init__(self) -> None:
        if self.mode not in ("package", "steps"):
            raise ValueError(f"slice {self.name}: mode must be package or steps, not {self.mode!r}")
        if not self.patterns:
            raise ValueError(f"slice {self.name}: needs at least one pattern")
        for pattern in self.patterns:
            if _bad_relative(pattern.replace("*", "x").replace("?", "x")):
                raise ValueError(f"slice {self.name}: pattern {pattern!r} must be a relative path with no .. segment")

    def manifest(self) -> dict[str, object]:
        return {
            "name": self.name,
            "patterns": list(self.patterns),
            "mode": self.mode,
            "args": list(self.args),
            "outputs": list(self.outputs),
            "description": self.description,
            "expected_classification": self.expected_classification,
        }


@dataclass
class SliceTarget:
    """One directory a slice selected, with how to build it."""

    path: str
    name: str
    root: str
    step: str
    command_args: list[str]
    output_prefix: str
    outputs: list[str]
    package: NestedPackage | None = None
    skipped: str = ""

    def manifest(self) -> dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "root": self.root,
            "step": self.step or None,
            "args": list(self.command_args),
            "output_prefix": self.output_prefix,
            "outputs": list(self.outputs),
            "package": self.package.manifest() if self.package else None,
            "skipped": self.skipped or None,
        }


@dataclass
class SliceSelection:
    slice: TargetSlice
    narrowed_by: tuple[str, ...] = ()
    targets: list[SliceTarget] = field(default_factory=list)

    @property
    def selected(self) -> list[SliceTarget]:
        return [target for target in self.targets if not target.skipped]

    @property
    def skipped(self) -> list[SliceTarget]:
        return [target for target in self.targets if target.skipped]

    def manifest(self) -> dict[str, object]:
        return {
            "slice": self.slice.name,
            "patterns": list(self.slice.patterns),
            "mode": self.slice.mode,
            "narrowed_by": list(self.narrowed_by),
            "selected_paths": [target.path for target in self.selected],
            "skipped": [{"path": target.path, "reason": target.skipped} for target in self.skipped],
            "targets": [target.manifest() for target in self.targets],
        }


def resolve_slice(
    repo: Path,
    target_slice: TargetSlice,
    narrow: tuple[str, ...] = (),
    known_steps: set[str] | None = None,
) -> SliceSelection:
    """Find what a slice selects in a clone.

    `narrow` adds globs, and a directory must match one of them as well. This
    is how a run picks one sample out of a slice. `known_steps`, when given, is
    the set of build steps the repo defines on this platform. A `steps` target
    whose step is absent is skipped with a reason and is not an error, since
    some samples build only on Windows.
    """
    selection = SliceSelection(target_slice, tuple(narrow))
    for package in discover_packages(repo):
        if not any(glob_match(pattern, package.path) for pattern in target_slice.patterns):
            continue
        if narrow and not any(glob_match(pattern, package.path) for pattern in narrow):
            continue
        base = posixpath.basename(package.path)
        if target_slice.mode == "package":
            if not package.has_manifest and not package.has_build_zig:
                continue
            target = SliceTarget(
                path=package.path,
                name=base,
                root=package.path,
                step="",
                command_args=list(target_slice.args),
                output_prefix=posixpath.join(package.path, "zig-out"),
                outputs=[output.format(name=base) for output in target_slice.outputs],
                package=package,
            )
        else:
            if not package.has_build_zig:
                continue
            target = SliceTarget(
                path=package.path,
                name=base,
                root="",
                step=base,
                command_args=[base, *target_slice.args],
                output_prefix="zig-out",
                outputs=[output.format(name=base) for output in target_slice.outputs],
                package=package,
            )
            if known_steps is not None and base not in known_steps:
                target.skipped = f"build step {base!r} is not defined for this target"
        selection.targets.append(target)
    return selection
