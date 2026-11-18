"""Read `build.zig.zon` and describe its package dependencies.

ZON is a small data subset of Zig. This parser covers what package manifests
use: anonymous structs and tuples, strings, multiline strings, numbers,
booleans, enum literals and comments. It keeps source spans, so one field can
be rewritten without touching the rest of the file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class ZonError(ValueError):
    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(f"{line}:{column}: {message}")
        self.line = line
        self.column = column


class EnumLiteral(str):
    """A `.name` value. It behaves as its bare name."""


@dataclass
class Node:
    """A parsed value with the source span it came from."""

    value: object
    start: int
    end: int
    # For a struct with field names: each field's node, in source order.
    fields: dict[str, "Node"] = field(default_factory=dict)
    # For a tuple: each element's node.
    items: list["Node"] = field(default_factory=list)


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?(0x[0-9a-fA-F_]+|0o[0-7_]+|0b[01_]+|[0-9][0-9_]*(\.[0-9_]+)?([eE][-+]?[0-9_]+)?)")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'"}


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def error(self, message: str, pos: int | None = None) -> ZonError:
        at = self.pos if pos is None else pos
        line = self.text.count("\n", 0, at) + 1
        column = at - (self.text.rfind("\n", 0, at) + 1) + 1
        return ZonError(message, line, column)

    def skip(self) -> None:
        text = self.text
        while self.pos < len(text):
            if text[self.pos] in " \t\r\n":
                self.pos += 1
            elif text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = len(text) if end < 0 else end
            else:
                return

    def peek(self, token: str) -> bool:
        self.skip()
        return self.text.startswith(token, self.pos)

    def expect(self, token: str) -> None:
        if not self.peek(token):
            raise self.error(f"expected {token!r}")
        self.pos += len(token)

    def string(self) -> str:
        assert self.text[self.pos] == '"'
        start = self.pos
        self.pos += 1
        out: list[str] = []
        while True:
            if self.pos >= len(self.text) or self.text[self.pos] == "\n":
                raise self.error("unterminated string", start)
            ch = self.text[self.pos]
            if ch == '"':
                self.pos += 1
                return "".join(out)
            if ch == "\\":
                nxt = self.text[self.pos + 1 : self.pos + 2]
                if nxt == "x":
                    out.append(chr(int(self.text[self.pos + 2 : self.pos + 4], 16)))
                    self.pos += 4
                elif nxt == "u":
                    close = self.text.index("}", self.pos)
                    out.append(chr(int(self.text[self.pos + 3 : close], 16)))
                    self.pos = close + 1
                elif nxt in _ESCAPES:
                    out.append(_ESCAPES[nxt])
                    self.pos += 2
                else:
                    raise self.error("unknown string escape")
            else:
                out.append(ch)
                self.pos += 1

    def multiline_string(self) -> str:
        lines = []
        while self.peek("\\\\"):
            end = self.text.find("\n", self.pos)
            end = len(self.text) if end < 0 else end
            lines.append(self.text[self.pos + 2 : end])
            self.pos = end
        return "\n".join(lines)

    def name(self) -> str:
        """An identifier or `@"quoted name"` after a leading dot."""
        if self.text.startswith('@"', self.pos):
            self.pos += 1
            return self.string()
        match = _IDENT.match(self.text, self.pos)
        if not match:
            raise self.error("expected a field or enum name")
        self.pos = match.end()
        return match.group(0)

    def value(self) -> Node:
        self.skip()
        start = self.pos
        text = self.text
        if text.startswith(".{", start):
            return self.struct()
        if text.startswith('"', start):
            return Node(self.string(), start, self.pos)
        if text.startswith("\\\\", start):
            return Node(self.multiline_string(), start, self.pos)
        if text.startswith(".", start):
            self.pos += 1
            return Node(EnumLiteral(self.name()), start, self.pos)
        match = _NUMBER.match(text, start)
        if match:
            self.pos = match.end()
            raw = match.group(0).replace("_", "")
            is_float = not raw.lower().startswith(("0x", "-0x")) and any(ch in raw for ch in ".eE")
            return Node(float(raw) if is_float else int(raw, 0), start, self.pos)
        match = _IDENT.match(text, start)
        if match and match.group(0) in ("true", "false", "null"):
            self.pos = match.end()
            return Node({"true": True, "false": False, "null": None}[match.group(0)], start, self.pos)
        raise self.error("expected a value")

    def struct(self) -> Node:
        start = self.pos
        self.pos += 2
        fields: dict[str, Node] = {}
        items: list[Node] = []
        while True:
            if self.peek("}"):
                self.pos += 1
                break
            checkpoint = self.pos
            named = False
            if self.text.startswith(".", self.pos) and not self.text.startswith(".{", self.pos):
                self.pos += 1
                key_pos = self.pos
                key = self.name()
                if self.peek("="):
                    self.pos += 1
                    if key in fields:
                        raise self.error(f"duplicate field {key!r}", key_pos)
                    fields[key] = self.value()
                    named = True
                else:
                    self.pos = checkpoint
            if not named:
                items.append(self.value())
            if fields and items:
                raise self.error("a struct cannot mix named fields and positional values", checkpoint)
            if self.peek(","):
                self.pos += 1
            elif not self.peek("}"):
                raise self.error("expected ',' or '}'")
        if items:
            return Node([item.value for item in items], start, self.pos, items=items)
        return Node({key: node.value for key, node in fields.items()}, start, self.pos, fields=fields)


def parse_node(text: str) -> Node:
    parser = _Parser(text)
    node = parser.value()
    parser.skip()
    if parser.pos != len(text):
        raise parser.error("unexpected text after the top-level value")
    return node


def parse(text: str) -> object:
    """Parse ZON text into dicts, lists, strings, numbers, booleans and EnumLiterals."""
    return parse_node(text).value


# --- package dependencies ----------------------------------------------------

_LEGACY_HASH = re.compile(r"^1220[0-9a-f]{64}$")
# "<name>-<version>-<digest>". The digest is always 44 base64url characters, so
# a pre-release version such as "0.11.0-dev" is told apart from it by length.
_NAMED_HASH = re.compile(r"^(?P<name>[A-Za-z0-9_]+)-(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)-(?P<digest>[A-Za-z0-9_-]{44})$")


@dataclass(frozen=True)
class Dependency:
    """One entry of `.dependencies`, plus what its url and hash imply.

    `alias` is the name the build script passes to `b.dependency`. It can
    differ from `package_name`, the name the package gives itself, which newer
    hashes embed.
    """

    alias: str
    url: str = ""
    hash: str = ""
    path: str = ""
    lazy: bool = False

    @property
    def source(self) -> str:
        """Where the package comes from: path, git, zip, tarball, or archive."""
        if self.path:
            return "path"
        base = self.url.split("#", 1)[0].split("?", 1)[0].lower()
        if self.url.startswith("git+"):
            return "git"
        if base.endswith(".zip"):
            return "zip"
        if base.endswith((".tar", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.zst", ".tar.bz2")):
            return "tarball"
        return "archive"

    @property
    def hash_format(self) -> str:
        """How the hash is written.

        legacy-multihash  a "1220..." hex digest, used before Zig 0.14. A
                          package pinned this way usually predates the
                          `.name = .enum_literal` and `.fingerprint` manifest
                          rules, so newer Zig can reject its build.zig.zon.
        name-version      "<name>-<version>-<digest>", Zig 0.14 and later.
        nameless          "N-V-__...", a package with no manifest name.
        none              no hash, as for a path dependency.
        """
        if not self.hash:
            return "none"
        if _LEGACY_HASH.match(self.hash):
            return "legacy-multihash"
        if self.hash.startswith("N-V-__"):
            return "nameless"
        if _NAMED_HASH.match(self.hash):
            return "name-version"
        return "unknown"

    @property
    def package_name(self) -> str:
        match = _NAMED_HASH.match(self.hash)
        return match.group("name") if match else ""

    @property
    def package_version(self) -> str:
        match = _NAMED_HASH.match(self.hash)
        return match.group("version") if match else ""

    @property
    def git_ref(self) -> str:
        if self.source == "git" and "#" in self.url:
            return self.url.rsplit("#", 1)[1]
        return ""

    def manifest(self) -> dict[str, object]:
        data: dict[str, object] = {"alias": self.alias, "source": self.source, "lazy": self.lazy}
        for key in ("url", "hash", "path"):
            value = getattr(self, key)
            if value:
                data[key] = value
        data["hash_format"] = self.hash_format
        for key in ("package_name", "package_version", "git_ref"):
            value = getattr(self, key)
            if value:
                data[key] = value
        return data


def dependencies(manifest: object) -> list[Dependency]:
    """The `.dependencies` of a parsed build.zig.zon, in source order."""
    if not isinstance(manifest, dict):
        raise ValueError("build.zig.zon must be a struct")
    raw = manifest.get("dependencies", {})
    if isinstance(raw, list) and not raw:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(".dependencies must be a struct of named dependencies")
    result = []
    for alias, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"dependency {alias!r} must be a struct")
        result.append(
            Dependency(
                alias=alias,
                url=str(entry.get("url", "")),
                hash=str(entry.get("hash", "")),
                path=str(entry.get("path", "")),
                lazy=bool(entry.get("lazy", False)),
            )
        )
    return result


def read_dependencies(text: str) -> list[Dependency]:
    return dependencies(parse(text))


def field_name(name: str) -> str:
    """Spell a field name the way ZON needs it."""
    return name if _IDENT.fullmatch(name) else '@"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_dependencies(deps: list[Dependency], indent: str = "    ") -> str:
    """The `.{ ... }` value for a `.dependencies` field."""
    if not deps:
        return ".{}"
    lines = [".{"]
    for dep in deps:
        lines.append(f"{indent * 2}.{field_name(dep.alias)} = .{{")
        for key in ("url", "hash", "path"):
            value = getattr(dep, key)
            if value:
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{indent * 3}.{key} = "{escaped}",')
        if dep.lazy:
            lines.append(f"{indent * 3}.lazy = true,")
        lines.append(f"{indent * 2}}},")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def replace_dependencies(text: str, deps: list[Dependency]) -> str:
    """Rewrite only the `.dependencies` value of a build.zig.zon."""
    root = parse_node(text)
    node = root.fields.get("dependencies")
    if node is None:
        raise ValueError("build.zig.zon has no .dependencies field to rewrite")
    return text[: node.start] + render_dependencies(deps) + text[node.end :]


def diff_dependencies(declared: list[Dependency], actual: list[Dependency]) -> list[str]:
    """Human-readable differences between two dependency lists, by alias."""
    problems: list[str] = []
    have = {dep.alias: dep for dep in actual}
    want = {dep.alias: dep for dep in declared}
    for alias, dep in want.items():
        other = have.get(alias)
        if other is None:
            problems.append(f"package {alias!r} is declared in project.cue but missing from build.zig.zon")
            continue
        for key in ("url", "hash", "path", "lazy"):
            if getattr(dep, key) != getattr(other, key):
                problems.append(
                    f"package {alias!r} {key} differs: project.cue has {getattr(dep, key)!r}, "
                    f"build.zig.zon has {getattr(other, key)!r}"
                )
    for alias in have:
        if alias not in want:
            problems.append(f"dependency {alias!r} is in build.zig.zon but not declared in project.cue packages")
    return problems


def dependency_lines(text: str) -> dict[str, tuple[int, int]]:
    """First and last source line of each dependency entry, by alias."""
    node = parse_node(text).fields.get("dependencies")
    if node is None:
        return {}
    spans = {}
    for alias, entry in node.fields.items():
        # The entry starts at its value. Walk back to the field name so an
        # error reported on the `.alias = ` line still maps to it.
        first = text.count("\n", 0, text.rfind("\n", 0, entry.start) + 1) + 1
        last = text.count("\n", 0, entry.end) + 1
        spans[alias] = (first, last)
    return spans


def render_cue_packages(deps: list[Dependency], indent: str = "    ") -> str:
    """A project.cue `packages` block that declares these dependencies."""
    lines = ["packages: {"]
    for dep in deps:
        lines.append(f"{indent}{json.dumps(dep.alias)}: {{")
        for key in ("url", "hash", "path"):
            if getattr(dep, key):
                lines.append(f"{indent * 2}{key}: {json.dumps(getattr(dep, key))}")
        if dep.lazy:
            lines.append(f"{indent * 2}lazy: true")
        lines.append(f"{indent}}}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def from_packages(packages: dict[str, dict[str, object]]) -> list[Dependency]:
    """Dependencies for an exported project.cue `packages` map."""
    return [
        Dependency(
            alias=alias,
            url=str(entry.get("url", "")),
            hash=str(entry.get("hash", "")),
            path=str(entry.get("path", "")),
            lazy=bool(entry.get("lazy", False)),
        )
        for alias, entry in packages.items()
    ]
