"""Typed dependency options: check them before `std.Build` can panic.

A package use in project.cue passes `args` to the dependency's build function.
Zig reads those as a struct literal, so a wrong name or type shows up late and
reads badly. This module checks them early.

Structure. `arg_errors` checks one package use on its own: the option names are
unique, each value fits its kind, and a forwarded `target` or `optimize` is not
passed twice. The generator applies the same rules.

Against the dependency. When the dependency's `build.zig` is on disk, as it is
for a `path` package or a fetched package in the Zig cache, `scan_build_script`
lists the options it declares with `b.option`, `standardTargetOptions` and
`standardOptimizeOption`. `check_against` compares each arg with them: the name
must exist, the kind must match the declared type, and an enum tag must be one
the option's enum defines. A dependency that declares no option at all is
skipped, since it may read them through helpers this scan cannot follow. An arg
with `unchecked: true` is skipped too.
"""

from __future__ import annotations

import difflib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ARG_KINDS = ("bool", "int", "string", "string_list", "enum", "target", "optimize")
OPTIMIZE_MODES = ("Debug", "ReleaseSafe", "ReleaseFast", "ReleaseSmall")
_TARGET_TEXT = re.compile(r"^[A-Za-z0-9_.+-]+$")
_INT_TYPE = re.compile(r"^(?:[iu]\d+|usize|isize|c_u?(?:short|int|long|longlong))$")


def _kind_label(value: object) -> str:
    if isinstance(value, bool):
        return "a bool"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "a list"
    return f"a {type(value).__name__}"


def arg_errors(owner: str, item: dict) -> list[str]:
    """Problems with one package use's `args`, independent of the dependency."""
    errors: list[str] = []
    seen: set[str] = set()
    implicit = []
    if item.get("pass_target", True):
        implicit.append("target")
    if item.get("pass_optimize", True):
        implicit.append("optimize")
    seen.update(implicit)
    for arg in item.get("args") or []:
        name = arg.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{owner}: a dependency option needs a non-empty name")
            continue
        where = f"{owner}: option {name!r}"
        if name in seen:
            hint = f"; set pass_{name}: false to give it your own value" if name in implicit else ""
            errors.append(f"{where} is passed twice{hint}")
        seen.add(name)
        kind = arg.get("kind")
        value = arg.get("value")
        if kind not in ARG_KINDS:
            errors.append(f"{where} has kind {kind!r}; the supported kinds are {', '.join(ARG_KINDS)}")
        elif kind == "bool" and not isinstance(value, bool):
            errors.append(f"{where} is a bool and was given {_kind_label(value)}: {value!r}")
        elif kind == "int" and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"{where} is an int and was given {_kind_label(value)}: {value!r}")
        elif kind == "string" and not isinstance(value, str):
            errors.append(f"{where} is a string and was given {_kind_label(value)}: {value!r}")
        elif kind == "string_list" and not (isinstance(value, list) and all(isinstance(i, str) for i in value)):
            errors.append(f"{where} is a string_list and needs a list of strings: {value!r}")
        elif kind == "enum" and not (isinstance(value, str) and value):
            errors.append(f"{where} is an enum and needs a tag name: {value!r}")
        elif kind == "target" and not (isinstance(value, str) and (value == "forward" or _TARGET_TEXT.match(value))):
            errors.append(f'{where} is a target and needs "forward" or a target triple: {value!r}')
        elif kind == "optimize" and not (value == "forward" or value in OPTIMIZE_MODES):
            errors.append(f'{where} is an optimize mode and needs "forward" or one of {", ".join(OPTIMIZE_MODES)}: {value!r}')
    return errors


@dataclass(frozen=True)
class Declared:
    """One option a dependency's build script declares."""

    name: str
    kind: str  # an arg kind, "float", "lazy_path" or "other"
    type_text: str
    line: int
    tags: tuple[str, ...] | None = None


@dataclass
class Scan:
    options: dict[str, Declared] = field(default_factory=dict)
    path: str = "build.zig"

    @property
    def usable(self) -> bool:
        return bool(self.options)


_OPTION_CALL = re.compile(r"\b[A-Za-z_]\w*\.option\(")


def _split_top_level(text: str, start: int) -> list[str]:
    """The arguments of the call whose `(` ends at `start`, up to its closing `)`."""
    args: list[str] = []
    depth = 0
    current: list[str] = []
    i = start
    while i < len(text):
        char = text[i]
        if char == '"':
            j = i + 1
            while j < len(text) and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            current.append(text[i : j + 1])
            i = j + 1
            continue
        if char == "/" and text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                args.append("".join(current).strip())
                return args
            depth -= 1
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(char)
        i += 1
    return args


def _enum_tags(text: str, type_name: str) -> tuple[str, ...] | None:
    short = type_name.split(".")[-1]
    match = re.search(rf"\b(?:pub\s+)?const\s+{re.escape(short)}\s*=\s*enum\b[^{{]*\{{", text)
    if not match:
        return None
    body = []
    depth = 1
    for char in text[match.end():]:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        body.append(char)
    cleaned = re.sub(r"//[^\n]*", "", "".join(body))
    tags = []
    for part in cleaned.split(","):
        part = part.strip()
        if not part or part.startswith(("fn ", "pub ")):
            continue
        name = re.match(r'(@"[^"]*"|[A-Za-z_]\w*)', part)
        if name:
            tags.append(name.group(1).replace('@"', "").replace('"', ""))
    return tuple(tags)


def classify_type(type_text: str, source: str) -> tuple[str, tuple[str, ...] | None]:
    text = re.sub(r"\s+", " ", type_text.strip()).lstrip("?").strip()
    if text == "bool":
        return "bool", None
    if text == "[]const u8":
        return "string", None
    if text == "[]const []const u8":
        return "string_list", None
    if _INT_TYPE.match(text) or text == "comptime_int":
        return "int", None
    if text in ("f16", "f32", "f64", "f80", "f128"):
        return "float", None
    if text.endswith("LazyPath"):
        return "lazy_path", None
    if text in ("std.builtin.OptimizeMode", "OptimizeMode"):
        return "optimize", OPTIMIZE_MODES
    if text == "std.builtin.GlobalLinkage":
        return "enum", ("internal", "strong", "weak", "link_once")
    if re.fullmatch(r"[A-Za-z_][\w.]*", text):
        return "enum", _enum_tags(source, text)
    return "other", None


def scan_build_script(text: str, path: str = "build.zig") -> Scan:
    """The options a build script declares."""
    scan = Scan(path=path)
    for match in _OPTION_CALL.finditer(text):
        args = _split_top_level(text, match.end())
        if len(args) < 2 or not (args[1].startswith('"') and args[1].endswith('"')):
            continue
        name = args[1][1:-1]
        kind, tags = classify_type(args[0], text)
        line = text.count("\n", 0, match.start()) + 1
        scan.options.setdefault(name, Declared(name, kind, args[0].strip(), line, tags))
    for call, name, kind, type_text in (
        ("standardTargetOptions(", "target", "target", "std.Build.ResolvedTarget"),
        ("standardOptimizeOption(", "optimize", "optimize", "std.builtin.OptimizeMode"),
    ):
        index = text.find(call)
        if index >= 0:
            line = text.count("\n", 0, index) + 1
            scan.options.setdefault(name, Declared(name, kind, type_text, line, OPTIMIZE_MODES if kind == "optimize" else None))
    return scan


def _global_cache_roots() -> list[Path]:
    roots = []
    if os.environ.get("ZIG_GLOBAL_CACHE_DIR"):
        roots.append(Path(os.environ["ZIG_GLOBAL_CACHE_DIR"]))
    home = Path.home()
    roots.extend([home / ".cache" / "zig", home / "Library" / "Caches" / "zig"])
    return roots


def package_directory(root: Path, entry: dict) -> Path | None:
    """Where a package's sources are on disk, if they are."""
    if entry.get("path"):
        candidate = (root / entry["path"]).resolve()
        return candidate if candidate.is_dir() else None
    digest = entry.get("hash")
    if digest:
        for cache in _global_cache_roots():
            candidate = cache / "p" / digest
            if candidate.is_dir():
                return candidate
    return None


def check_against(owner: str, package: str, item: dict, scan: Scan) -> list[str]:
    """Compare a package use's explicit args with what the dependency declares."""
    errors: list[str] = []
    declared = scan.options
    for arg in item.get("args") or []:
        name = arg.get("name")
        kind = arg.get("kind")
        if arg.get("unchecked") or not isinstance(name, str) or kind not in ARG_KINDS:
            continue
        where = f"{owner}: option {name!r} for package {package!r}"
        option = declared.get(name)
        if option is None:
            close = difflib.get_close_matches(name, list(declared), n=1)
            hint = f"; did you mean {close[0]!r}?" if close else ""
            errors.append(
                f"{where} is not declared by {scan.path} (declared: {', '.join(sorted(declared))}){hint}"
            )
            continue
        if option.kind != kind:
            errors.append(
                f"{where} is passed as {kind}, but {scan.path}:{option.line} declares it as {option.type_text}"
                f" ({option.kind})"
            )
            continue
        value = arg.get("value")
        if kind == "enum" and option.tags is not None and value not in option.tags:
            errors.append(
                f"{where} is given tag {value!r}, which its enum does not define"
                f" (tags: {', '.join(option.tags)}; {scan.path}:{option.line})"
            )
    return errors


def package_use_errors(owner: str, package: str, item: dict, packages: dict, root: Path) -> list[str]:
    """`arg_errors`, then the check against the dependency's own build script."""
    errors = arg_errors(owner, item)
    if errors or not item.get("args"):
        return errors
    entry = packages.get(package)
    if not isinstance(entry, dict):
        return errors
    directory = package_directory(root, entry)
    script = directory / "build.zig" if directory else None
    if script is None or not script.is_file():
        return errors
    scan = scan_build_script(script.read_text(encoding="utf-8", errors="replace"), f"{package}/build.zig")
    if not scan.usable:
        return errors
    return check_against(owner, package, item, scan)


if __name__ == "__main__":
    # `python3 tools/dep_options.py path/to/build.zig` lists the declared options.
    for target in sys.argv[1:]:
        found = scan_build_script(Path(target).read_text(encoding="utf-8"), target)
        for option in found.options.values():
            tags = f" tags={','.join(option.tags)}" if option.tags else ""
            print(f"{option.name}: {option.kind} ({option.type_text}) line {option.line}{tags}")
