"""Package dependency metadata and failure diagnosis for corpus repos.

The metadata comes from the repo's own files: `build.zig.zon` is parsed, and
`build.zig` is scanned for how each dependency is used. A failed build is then
explained by matching Zig's error output against that metadata, so nobody has
to read the upstream build script to learn which dependency broke and why.
"""

from __future__ import annotations

import re
from pathlib import Path

import zon

FETCH = "dependency-fetch"
FORMAT = "dependency-format"

# Messages Zig prints for a dependency, in the order they are tested. Each maps
# to (classification, reason code, explanation).
#
# Some of these phrases are ordinary compiler errors too. Those in _LOCATED_ONLY
# count only when Zig reports them at a position inside a build.zig.zon.
_LOCATED_ONLY = ("expected enum literal", "invalid hash", "hash mismatch", "unable to unpack")
_REASONS: tuple[tuple[str, str, str, str], ...] = (
    ("name must be a valid bare zig identifier", FORMAT, "legacy-name",
     "its build.zig.zon still writes .name as a string, which this Zig rejects"),
    ("expected enum literal", FORMAT, "legacy-name",
     "its build.zig.zon still writes .name as a string, which this Zig rejects"),
    ("missing top-level 'fingerprint' field", FORMAT, "missing-fingerprint",
     "its build.zig.zon has no .fingerprint, which this Zig requires"),
    ("invalid fingerprint", FORMAT, "invalid-fingerprint",
     "its build.zig.zon carries a .fingerprint that does not match its name"),
    ("invalid hash", FORMAT, "invalid-hash",
     "its hash is written in a format this Zig does not accept"),
    ("dependency is missing hash field", FORMAT, "missing-hash",
     "the manifest gives a url without a hash"),
    ("hash mismatch", FETCH, "hash-mismatch",
     "the fetched content does not match the declared hash"),
    ("failed to create temporary zip file", FETCH, "zip-temp-file",
     "Zig could not create the temporary file it unpacks a zip archive through"),
    ("unable to connect to server", FETCH, "connection",
     "the host could not be reached"),
    ("Could not resolve host", FETCH, "connection",
     "the host name could not be resolved"),
    ("bad HTTP response code", FETCH, "http-status",
     "the server answered with an error status"),
    ("invalid HTTP response", FETCH, "http-response",
     "the server sent a response Zig could not read"),
    ("unable to discover remote git server capabilities", FETCH, "git-protocol",
     "the git server did not answer the protocol handshake"),
    ("unable to unpack", FETCH, "unpack",
     "the archive could not be unpacked"),
)

_ZON_ERROR = re.compile(r"^(?P<file>[^\n:]*build\.zig\.zon):(?P<line>\d+):(?P<column>\d+): error: (?P<message>.*)$", re.M)
_PACKAGE_DIR = re.compile(r"(?:^|/)(?:p|zig-pkg)/(?P<hash>[^/\s]+)/")
# Zig unpacks an archive under <cache>/tmp/<random>/ and reads the package's
# manifest there, before the package has a hash-named directory.
_UNPACK_DIR = re.compile(r"/tmp/(?:[0-9a-f]{16}|<random>)/(?P<dir>[^/\s]+)/build\.zig\.zon$")
_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.zst", ".tar.bz2", ".tar", ".zip")


def _unpacked_from(entry: dict[str, object], directory: str) -> bool:
    """Whether an unpacked archive directory plausibly came from this dependency.

    Hosts name the top directory of an archive after the repository and the
    ref, as in `zig-objc-362d12f4...` for `.../zig-objc/archive/362d12f4....zip`.
    """
    url = str(entry.get("url", ""))
    if not url:
        return False
    ref = str(entry.get("git_ref", ""))
    if ref and ref in directory:
        return True
    path = url.split("#", 1)[0].split("?", 1)[0]
    stem = path.rsplit("/", 1)[-1]
    for suffix in _ARCHIVE_SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if len(stem) >= 7 and stem in directory:
        return True
    return any(len(part) >= 3 and directory.startswith(part + "-") for part in path.split("/")[3:])


def classify(output: str) -> tuple[str, str, str] | None:
    """Classify dependency trouble in build output.

    Returns (classification, reason, matched message), or None when the output
    shows no dependency failure this module knows.
    """
    for match in _ZON_ERROR.finditer(output):
        for needle, classification, reason, _ in _REASONS:
            if needle in match.group("message"):
                return classification, reason, match.group("message")
    for needle, classification, reason, _ in _REASONS:
        if needle not in _LOCATED_ONLY and needle in output:
            return classification, reason, needle
    return None


def _call_end(text: str, open_paren: int) -> int:
    """Index just past the parenthesis that closes the one at `open_paren`."""
    depth = 0
    i = open_paren
    while i < len(text):
        ch = text[i]
        if ch == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


_DEP_CALL = re.compile(r"\b(?:lazyDependency|dependency)\(\s*\"(?P<name>[^\"]+)\"")
_ACCESS = r"\s*\.\s*(?P<kind>module|artifact|namedLazyPath|path|namedWriteFiles)\(\s*\"(?P<what>[^\"]*)\""


def scan_build_script(text: str) -> dict[str, dict[str, list[str]]]:
    """Find how a build.zig uses each dependency.

    This is a text scan, so it is a best effort. It follows the common shapes:
    a dependency bound to a constant or an `if (...) |dep|` capture, a chained
    `.module("x")`, and an `addImport("alias", ...)` or `.{ .name = "alias",
    .module = ... }` that names such a module.
    """
    usage: dict[str, dict[str, list[str]]] = {}

    def note(dep: str, kind: str, value: str) -> None:
        bucket = usage.setdefault(dep, {"modules": [], "artifacts": [], "paths": [], "import_aliases": []})
        if value not in bucket[kind]:
            bucket[kind].append(value)

    kinds = {"module": "modules", "artifact": "artifacts", "namedLazyPath": "paths", "path": "paths", "namedWriteFiles": "paths"}
    dep_vars: dict[str, str] = {}
    module_vars: dict[str, str] = {}

    for call in _DEP_CALL.finditer(text):
        dep = call.group("name")
        usage.setdefault(dep, {"modules": [], "artifacts": [], "paths": [], "import_aliases": []})
        end = _call_end(text, text.index("(", call.start()))
        chained = re.match(_ACCESS, text[end:])
        if chained:
            note(dep, kinds[chained.group("kind")], chained.group("what"))
        # `const x = b.dependency(...)`, possibly through `orelse` or `if`.
        line_start = text.rfind("\n", 0, call.start()) + 1
        binding = re.search(r"\b(?:const|var)\s+(\w+)\s*(?::[^=]+)?=\s*[^;\n]*$", text[line_start : call.start()])
        if binding:
            target = module_vars if chained and chained.group("kind") == "module" else dep_vars
            target[binding.group(1)] = dep
        capture = re.match(r"\s*\)\s*\|(\w+)\|", text[end:])
        if capture:
            dep_vars[capture.group(1)] = dep

    for var, dep in dep_vars.items():
        for access in re.finditer(r"\b" + re.escape(var) + _ACCESS, text):
            note(dep, kinds[access.group("kind")], access.group("what"))
        for binding in re.finditer(r"\b(?:const|var)\s+(\w+)\s*=\s*[^;]*?\b" + re.escape(var) + r"\s*\.\s*module\(", text):
            module_vars[binding.group(1)] = dep

    alias_forms = (
        r"addImport\(\s*\"(?P<alias>[^\"]+)\"\s*,\s*(?P<expr>[^;]*?)\)\s*;",
        r"\.name\s*=\s*\"(?P<alias>[^\"]+)\"\s*,\s*\.module\s*=\s*(?P<expr>[^}]*)\}",
    )
    for form in alias_forms:
        for match in re.finditer(form, text):
            expr = match.group("expr")
            for var, dep in list(module_vars.items()) + list(dep_vars.items()):
                if re.search(r"\b" + re.escape(var) + r"\b", expr):
                    note(dep, "import_aliases", match.group("alias"))
                    break
            else:
                inline = _DEP_CALL.search(expr)
                if inline:
                    note(inline.group("name"), "import_aliases", match.group("alias"))
    return usage


def describe(repo_path: Path) -> dict[str, object]:
    """Everything the corpus records about a repo's package dependencies."""
    manifest_path = repo_path / "build.zig.zon"
    if not manifest_path.is_file():
        return {"manifest": None, "dependencies": [], "summary": {"count": 0}, "note": "the repo has no build.zig.zon"}
    text = manifest_path.read_text(encoding="utf-8", errors="replace")
    try:
        parsed = zon.parse(text)
        deps = zon.dependencies(parsed)
        lines = zon.dependency_lines(text)
    except (zon.ZonError, ValueError) as exc:
        return {"manifest": "build.zig.zon", "dependencies": [], "summary": {"count": 0}, "error": f"build.zig.zon: {exc}"}

    usage: dict[str, dict[str, list[str]]] = {}
    script = repo_path / "build.zig"
    script_text = script.read_text(encoding="utf-8", errors="replace") if script.is_file() else ""
    if script_text:
        usage = scan_build_script(script_text)

    entries = []
    for dep in deps:
        entry = dep.manifest()
        first, last = lines.get(dep.alias, (0, 0))
        entry["manifest"] = "build.zig.zon"
        entry["manifest_lines"] = [first, last]
        used = usage.get(dep.alias)
        # A package can also be imported by the build script itself, as
        # `@import("<alias>")`, to use its build helpers.
        entry["imported_by_build_script"] = f'@import("{dep.alias}")' in script_text
        entry["used_by_build_script"] = used is not None or entry["imported_by_build_script"]
        entry.update(used or {"modules": [], "artifacts": [], "paths": [], "import_aliases": []})
        entries.append(entry)

    def count(key: str) -> dict[str, int]:
        totals: dict[str, int] = {}
        for entry in entries:
            totals[str(entry[key])] = totals.get(str(entry[key]), 0) + 1
        return dict(sorted(totals.items()))

    nested = _nested(repo_path, deps)
    nested_sources: dict[str, int] = {}
    for entry in nested:
        nested_sources[str(entry["source"])] = nested_sources.get(str(entry["source"]), 0) + 1
    info: dict[str, object] = {
        "manifest": "build.zig.zon",
        "dependencies": entries,
        # Dependencies of the path packages inside the repo, such as the ports
        # and tools of a workspace. Each records the chain of aliases that
        # leads to it and the manifest that declares it.
        "nested_dependencies": nested,
        "summary": {
            "count": len(entries),
            "lazy": sum(1 for entry in entries if entry["lazy"]),
            "by_source": count("source"),
            "by_hash_format": count("hash_format"),
            "nested_count": len(nested),
            "nested_by_source": dict(sorted(nested_sources.items())),
        },
    }
    if isinstance(parsed, dict):
        for key in ("name", "version", "minimum_zig_version"):
            if key in parsed:
                info[f"package_{key}" if key != "minimum_zig_version" else key] = str(parsed[key])
    return info


_MAX_NESTED = 2000


def _nested(repo_path: Path, direct: list[zon.Dependency]) -> list[dict[str, object]]:
    """Dependencies declared by the path packages a repo contains, at any depth."""
    found: list[dict[str, object]] = []
    root = repo_path.resolve()
    seen = {root / "build.zig.zon"}
    queue: list[tuple[Path, zon.Dependency, list[str]]] = [(root, dep, []) for dep in direct if dep.path]
    while queue and len(found) < _MAX_NESTED:
        base, dep, chain = queue.pop(0)
        package = (base / dep.path).resolve()
        manifest = package / "build.zig.zon"
        # Stay inside the repo, and visit each manifest once.
        if manifest in seen or root not in manifest.parents or not manifest.is_file():
            continue
        seen.add(manifest)
        text = manifest.read_text(encoding="utf-8", errors="replace")
        try:
            children = zon.read_dependencies(text)
            lines = zon.dependency_lines(text)
        except (zon.ZonError, ValueError):
            continue
        via = chain + [dep.alias]
        for child in children:
            entry = child.manifest()
            entry["via"] = via
            entry["manifest"] = manifest.relative_to(root).as_posix()
            entry["manifest_lines"] = list(lines.get(child.alias, (0, 0)))
            found.append(entry)
            if child.path:
                queue.append((package, child, via))
    return found


def _explain(entry: dict[str, object] | None, text: str, where: str) -> str:
    if entry is None:
        return f"{where}: {text}"
    origin = entry.get("url") or entry.get("path") or "no url"
    via = entry.get("via")
    through = f", reached through {' -> '.join(via)}" if via else ""  # type: ignore[arg-type]
    return f"dependency {entry['alias']} ({entry['source']}, {origin}{through}): {text}"


def diagnose(output: str, info: dict[str, object], repo_path: Path | None = None) -> dict[str, object] | None:
    """Name the dependency behind a fetch or format failure.

    `info` is the result of `describe`. Returns None when the output shows no
    dependency failure.
    """
    found = classify(output)
    if found is None:
        return None
    classification, reason, message = found
    explanation = next(text for needle, _, code, text in _REASONS if code == reason and needle in message)
    # Direct dependencies first, so they win when a nested package pins the same thing.
    entries: list[dict[str, object]] = list(info.get("dependencies", [])) + list(info.get("nested_dependencies", []))  # type: ignore[arg-type]
    by_hash: dict[str, dict[str, object]] = {}
    for entry in entries:
        if entry.get("hash"):
            by_hash.setdefault(str(entry["hash"]), entry)
    result: dict[str, object] = {
        "kind": "format" if classification == FORMAT else "fetch",
        "classification": classification,
        "reason": reason,
        "message": message,
        "dependency": "",
        "transitive": False,
        "candidates": [],
    }

    error = next((m for m in _ZON_ERROR.finditer(output) if m.group("message") == message), None)
    entry: dict[str, object] | None = None
    where = "build output"
    if error is not None:
        file = error.group("file")
        line = int(error.group("line"))
        package_dir = _PACKAGE_DIR.search(file)
        root_manifest = str(repo_path / "build.zig.zon") if repo_path is not None else "build.zig.zon"
        unpacked = _UNPACK_DIR.search(file)
        if unpacked is not None:
            # The error is in a package Zig has just unpacked and not yet named.
            directory = unpacked.group("dir")
            entry = next((item for item in entries if _unpacked_from(item, directory)), None)
            result["transitive"] = entry is None
            result["package_dir"] = directory
            where = f"unpacked package {directory}"
        elif package_dir is not None:
            # The error is inside a fetched package's own manifest.
            package_hash = package_dir.group("hash")
            entry = by_hash.get(package_hash)
            result["transitive"] = entry is None
            result["package_hash"] = package_hash
            where = f"package {package_hash}"
        else:
            # A manifest inside the repo: the root one, or a path package's.
            relative = "build.zig.zon" if file == root_manifest else file
            if repo_path is not None and file.startswith(str(repo_path) + "/"):
                relative = file[len(str(repo_path)) + 1 :]
            entry = next(
                (
                    item
                    for item in entries
                    if item.get("manifest") == relative and item["manifest_lines"][0] <= line <= item["manifest_lines"][1]
                ),
                None,
            )
            where = f"{relative} line {line}"
            file = relative
        result["manifest"] = file
        result["line"] = line

    if entry is None and error is None:
        # No location to go on. Offer the dependencies the failure can apply to.
        if reason == "zip-temp-file":
            candidates = [item for item in entries if item["source"] == "zip"]
        elif result["kind"] == "format":
            candidates = [item for item in entries if item["hash_format"] == "legacy-multihash"]
        else:
            candidates = []
        result["candidates"] = [item["alias"] for item in candidates]
        if len(candidates) == 1:
            entry = candidates[0]

    if entry is not None:
        result["dependency"] = entry["alias"]
        for key in ("source", "url", "path", "hash", "hash_format", "lazy", "via"):
            if key in entry:
                result[key] = entry[key]
    result["explanation"] = _explain(entry, explanation, where)
    if entry is None and result["candidates"]:
        result["explanation"] += "; likely one of: " + ", ".join(result["candidates"])  # type: ignore[arg-type]
    return result
