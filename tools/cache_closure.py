#!/usr/bin/env python3
"""The declared-input closure of an Azazel build, and the cache key computed from it.

A cache hit restores `zig-out` and skips the build, so a key that misses an
input makes a stale hit. This module names every input that can change an
artifact, hashes each one, and refuses to produce a key for a build whose
inputs it cannot name.

The inputs, by part of the key:

    model       the resolved CUE model: modules, native fields, packages with
                their typed args, options, profiles, generated steps, system deps
    engine      build.zig, compat.zig, the schema, the exporter, the generator,
                the CUE version, and this file's own version
    toolchain   the Zig binary: its reported version and its content hash
    target      the target, cpu and ABI: the `-Dtarget` and `-Dcpu` arguments, or
                the host's native description when they are absent
    options     the effective `-D` options, the selected slices and subprojects
    sources     every reachable Zig source, `@embedFile` and imported data file
    headers     every C or C++ source and the headers it includes, and every
                file under a declared include directory
    objects     every declared object file and library search directory
    installs    every file under a declared `install_dirs` source directory
    generated   generator tool sources, input files and stdin
    packages    the contents of each local `path` package, and the url and hash
                of each fetched one
    system      the host tools a build declares, by name

A build is refused, with a reason for each cause, when it has:

    pre or post commands            arbitrary programs with undeclared inputs
    a `command` generator           a program from PATH, with an unknown version
    a generator tool that reads     the environment, the clock, randomness or
    undeclared state                the network
    system libraries                `system_libs`, `pkg_config_libs`, `frameworks`
                                    and system_deps other than `tool`, whose
                                    contents the key cannot see
    link_libc without a fixed ABI   the native libc is a host input
    environment variables           that redirect the compiler, libc or SDK
    build arguments the closure     anything but the options listed above
    does not model
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import zig_toolchain  # noqa: E402

# Bump when the meaning of the key changes, so old cache entries stop matching.
KEY_VERSION = "2"

ENGINE_FILES = (
    "build.zig",
    "compat.zig",
    "build.zig.zon",
    "schema.cue",
    "project.cue",
    "export.cue",
    "gen_build_spec.sh",
)

# Directories that hold build output or version control, never inputs.
SKIP_DIRS = {".git", ".zig-cache", "zig-cache", "zig-out", ".azazel-install", "node_modules"}
SKIP_FILES = {"build_spec.zig", ".build_spec.stamp"}

# Compiler and loader redirections that change an artifact without appearing in
# any declared input.
REFUSED_ENV = (
    "ZIG_LIB_DIR",
    "ZIG_LIBC",
    "ZIG_BUILD_RUNNER",
    "SDKROOT",
    "DEVELOPER_DIR",
    "MACOSX_DEPLOYMENT_TARGET",
    "CPATH",
    "C_INCLUDE_PATH",
    "CPLUS_INCLUDE_PATH",
    "LIBRARY_PATH",
    "CC",
    "CXX",
    "CFLAGS",
    "CXXFLAGS",
    "LDFLAGS",
)

# `-D` options that build.zig reads itself, beside the project's own `options`.
BUILTIN_OPTIONS = ("target", "cpu", "dynamic-linker", "slice", "subproject")
LIST_OPTIONS = ("slice", "subproject")

# Arguments that change output formatting and nothing else.
NOISE_WITH_VALUE = ("--summary", "--color")

IMPORT_RE = re.compile(r"@import\(\s*\"([^\"]+)\"\s*\)")
EMBED_RE = re.compile(r"@embedFile\(\s*\"([^\"]+)\"\s*\)")
INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]+"([^"]+)"', re.MULTILINE)
C_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".inc", ".inl", ".c", ".cc", ".cpp", ".cxx", ".m", ".mm"}

# What a generator tool may not do, because the key cannot see the answer.
TOOL_HAZARDS = (
    (re.compile(r"\b(getEnvVarOwned|getEnvMap|getenv|getEnvVar|environ|EnvMap)\b"), "reads the environment"),
    (re.compile(r"\b(milliTimestamp|nanoTimestamp|timestamp|Instant\.now)\b"), "reads the clock"),
    (re.compile(r"std\.crypto\.random|std\.Random\.DefaultPrng|std\.rand\b"), "uses randomness"),
    (re.compile(r"std\.net\b|std\.http\.Client"), "uses the network"),
)


class ClosureError(RuntimeError):
    """The closure could not be computed at all, for example `cue` is missing."""


@dataclass
class Closure:
    """The result of walking a build's declared inputs."""

    key: str | None
    parts: dict[str, str] = field(default_factory=dict)
    files: dict[str, dict[str, str]] = field(default_factory=dict)
    refusals: list[str] = field(default_factory=list)

    @property
    def cacheable(self) -> bool:
        return not self.refusals

    def manifest(self) -> dict[str, object]:
        return {
            "key": self.key,
            "key_version": KEY_VERSION,
            "parts": self.parts,
            "files": self.files,
            "refusals": self.refusals,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_json(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class Hasher:
    """File digests, memoized for one closure walk."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self._files: dict[Path, str | None] = {}

    def rel(self, path: Path) -> str:
        return os.path.relpath(path, self.project).replace(os.sep, "/")

    def file(self, path: Path) -> str | None:
        path = Path(os.path.normpath(path))
        if path not in self._files:
            try:
                if path.is_symlink():
                    self._files[path] = sha256_bytes(("link:" + os.readlink(path)).encode())
                else:
                    self._files[path] = sha256_bytes(path.read_bytes())
            except OSError:
                self._files[path] = None
        return self._files[path]

    def tree(self, path: Path) -> dict[str, str] | None:
        """Every file under a directory, by relative path. None when it is not a directory."""
        path = Path(os.path.normpath(path))
        if not path.is_dir():
            return None
        found: dict[str, str] = {}
        for current, dirs, names in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(names):
                if name in SKIP_FILES:
                    continue
                full = Path(current) / name
                digest = self.file(full)
                if digest is not None:
                    found[self.rel(full)] = digest
        return found


@dataclass
class Walk:
    """The files collected for each part, and why a build was refused."""

    hasher: Hasher
    files: dict[str, dict[str, str]]
    refusals: list[str]

    def add(self, part: str, path: Path, what: str) -> bool:
        digest = self.hasher.file(path)
        if digest is None:
            self.refuse(f"{what} {self.hasher.rel(path)} is declared and cannot be read")
            return False
        self.files.setdefault(part, {})[self.hasher.rel(path)] = digest
        return True

    def add_tree(self, part: str, path: Path, what: str) -> None:
        tree = self.hasher.tree(path)
        if tree is None:
            self.refuse(f"{what} {self.hasher.rel(path)} is declared and is not a directory")
            return
        self.files.setdefault(part, {}).update(tree)

    def refuse(self, message: str) -> None:
        if message not in self.refusals:
            self.refusals.append(message)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def walk_zig(walk: Walk, roots: list[Path], what: str, part: str = "sources") -> list[Path]:
    """Add `roots` and everything they import or embed. Returns the files reached."""
    seen: set[Path] = set()
    stack = [Path(os.path.normpath(root)) for root in roots]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if not walk.add(part, current, what):
            continue
        text = read_text(current)
        base = current.parent
        for spec in IMPORT_RE.findall(text):
            candidate = Path(os.path.normpath(base / spec))
            # A bare name is a package, an alias or std. A path with a file
            # suffix is a source or data file next to the importer.
            if Path(spec).suffix and candidate.is_file() and candidate not in seen:
                stack.append(candidate)
        for spec in EMBED_RE.findall(text):
            candidate = Path(os.path.normpath(base / spec))
            if candidate.is_file():
                walk.add(part, candidate, "embedded file")
    return sorted(seen)


def walk_c(walk: Walk, source: Path, include_dirs: list[Path]) -> None:
    """Add a C or C++ source and every quoted include it reaches."""
    seen: set[Path] = set()
    stack = [Path(os.path.normpath(source))]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if not walk.add("headers", current, "C source" if current == source else "header"):
            continue
        for spec in INCLUDE_RE.findall(read_text(current)):
            for base in (current.parent, *include_dirs):
                candidate = Path(os.path.normpath(base / spec))
                if candidate.is_file():
                    stack.append(candidate)
                    break


def inside(path: str) -> bool:
    return not os.path.isabs(path)


def scan_tool(walk: Walk, name: str, reached: list[Path]) -> None:
    for path in reached:
        text = read_text(path)
        for pattern, reason in TOOL_HAZARDS:
            if pattern.search(text):
                walk.refuse(
                    f"generated step {name!r} tool source {walk.hasher.rel(path)} {reason}; "
                    "its output is not a function of declared inputs"
                )


# Interpreters whose script argument the closure can read and scan.
INTERPRETERS = {"python3": "python", "python": "python", "sh": "shell", "bash": "shell"}

SCRIPT_HAZARDS = {
    "python": (
        (re.compile(r"\bos\.(environ|getenv|putenv)\b|\bgetenv\b|\benviron\b"), "reads the environment"),
        (re.compile(r"\b(time\.time|time\.time_ns|datetime|uuid|random|secrets)\b"), "reads the clock or randomness"),
        (re.compile(r"\b(socket|urllib|http\.client|requests|ftplib|smtplib)\b"), "uses the network"),
        (re.compile(r"\b(subprocess|os\.system|os\.popen|os\.exec\w*|shutil\.which)\b"), "runs other programs"),
    ),
    "shell": (
        (re.compile(r"\$\{?[A-Za-z_][A-Za-z_0-9]*|\benv\b|\bprintenv\b|\bdate\b|\$RANDOM|\bcurl\b|\bwget\b"),
         "reads variables, the environment, the clock or the network"),
    ),
}


def scan_command(walk: Walk, name: str, gen: dict, project: Path) -> None:
    """Admit a `command` generator only when it is an interpreter running a script.

    The interpreter binary goes into the key by content. The script is an input
    file, so it is hashed and scanned for reads of the environment, the clock,
    randomness, the network and other programs. Any other program is a binary
    whose behaviour the closure cannot read, so it is refused.
    """
    program = gen["command"][0]
    kind = INTERPRETERS.get(os.path.basename(program))
    if kind is None:
        walk.refuse(
            f"generated step {name!r} runs {program!r} from PATH; only an interpreter "
            "running a declared script can be cached, because other programs are not readable"
        )
        return
    resolved = shutil.which(program)
    if resolved is None:
        walk.refuse(f"generated step {name!r} runs {program!r}, which is not on PATH")
        return
    interpreter = Path(os.path.realpath(resolved))
    digest = walk.hasher.file(interpreter)
    if digest is not None:
        walk.files.setdefault("generated", {})[f"interpreter:{os.path.basename(program)}"] = digest
    scripts = [
        project / arg["value"]
        for arg in gen.get("args", [])
        if arg.get("kind") == "input_file" and Path(arg["value"]).suffix in {".py", ".sh"}
    ]
    if not scripts:
        walk.refuse(f"generated step {name!r} runs {program!r} without a script among its input files")
        return
    for script in scripts:
        text = read_text(script)
        for pattern, reason in SCRIPT_HAZARDS[kind]:
            if pattern.search(text):
                walk.refuse(
                    f"generated step {name!r} script {walk.hasher.rel(script)} {reason}; "
                    "its output is not a function of declared inputs"
                )


def export_model(project: Path) -> dict:
    cue = shutil.which("cue")
    if cue is None:
        raise ClosureError("`cue` is not on PATH")
    result = subprocess.run(
        [cue, "export", "-e", "build"], cwd=project, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise ClosureError("cue export failed: " + (result.stderr.strip() or "no output"))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClosureError(f"cue export returned invalid JSON: {exc}") from exc


def cue_version() -> str:
    cue = shutil.which("cue")
    if cue is None:
        return "missing"
    result = subprocess.run([cue, "version"], text=True, capture_output=True, check=False)
    return result.stdout.strip()


_ZIG_DIGESTS: dict[tuple[str, int, int], str] = {}


def zig_identity(zig: str | None, refusals: list[str]) -> dict[str, str]:
    """Version and content hash of the Zig binary that will run the build."""
    path = zig or shutil.which("zig")
    if not path:
        refusals.append("zig is not on PATH, so the toolchain identity is unknown")
        return {}
    version = zig_toolchain.zig_version_of(path)
    if not version:
        refusals.append(f"{path} did not report a version, so the toolchain identity is unknown")
        return {}
    resolved = os.path.realpath(path)
    stat = os.stat(resolved)
    memo = (resolved, stat.st_mtime_ns, stat.st_size)
    if memo not in _ZIG_DIGESTS:
        digest = hashlib.sha256()
        with open(resolved, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        _ZIG_DIGESTS[memo] = digest.hexdigest()
    return {"version": version, "binary_sha256": _ZIG_DIGESTS[memo]}


_NATIVE: dict[str, str] = {}


def native_target(zig: str | None) -> str:
    """The host's native target, cpu model and features, as Zig reports them."""
    path = zig or shutil.which("zig")
    if not path:
        return "unknown"
    if path not in _NATIVE:
        _NATIVE[path] = _read_native_target(path)
    return _NATIVE[path]


def _read_native_target(path: str) -> str:
    try:
        result = subprocess.run([path, "targets"], text=True, capture_output=True, check=False)
    except OSError:
        return "unknown"
    text = result.stdout
    start = text.find(".native = .{")
    if result.returncode == 0 and start >= 0:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    return re.sub(r"\s+", " ", text[start:index + 1])
    try:
        env = subprocess.run([path, "env"], text=True, capture_output=True, check=False)
    except OSError:
        return "unknown"
    match = re.search(r'"target":\s*"([^"]+)"', env.stdout)
    return match.group(1) if match else "unknown"


def parse_build_args(args: list[str], declared: list[dict], walk: Walk) -> dict[str, object]:
    """Reduce `zig build` arguments to the effective values the closure models."""
    option_defs = {option["name"]: option for option in declared}
    given: dict[str, list[str]] = {}
    steps: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in NOISE_WITH_VALUE:
            index += 2
            continue
        if re.fullmatch(r"-j\d+", arg):
            index += 1
            continue
        if arg.startswith("-D"):
            name, has_value, value = arg[2:].partition("=")
            if name not in BUILTIN_OPTIONS and name not in option_defs:
                walk.refuse(f"build option -D{name} is not declared in project.cue options, so the key cannot model it")
            else:
                given.setdefault(name, []).append(value if has_value else "true")
        elif arg.startswith("-"):
            walk.refuse(f"build argument {arg} changes the build in a way the key does not model")
        else:
            steps.append(arg)
        index += 1

    effective: dict[str, object] = {}
    for name in sorted(given):
        values = given[name]
        if name in LIST_OPTIONS:
            effective[name] = sorted(values)
        else:
            effective[name] = values[-1]
    for name, option in sorted(option_defs.items()):
        value = effective.get(name)
        if value is None and "default" in option:
            value = option["default"]
        if value is None:
            value = {"bool": False, "string": "", "u32": 0}.get(option.get("type"), "")
        if option.get("type") == "bool":
            value = str(value).lower() in ("true", "1", "yes", "y")
        elif option.get("type") == "u32":
            try:
                value = int(str(value), 0)
            except ValueError:
                walk.refuse(f"build option -D{name} is not an integer: {value!r}")
        effective[name] = value
    effective["steps"] = sorted(steps)
    return effective


def explicit_abi_target(target: str | None) -> bool:
    """True for `arch-os-abi` with every part named and the OS not Apple's."""
    if not target:
        return False
    parts = target.split("-")
    if len(parts) < 3 or not all(parts):
        return False
    return parts[1].split(".")[0] not in {"macos", "ios", "tvos", "watchos", "visionos", "darwin"}


def collect(project: Path, model: dict, args: list[str], env: dict[str, str], walk: Walk) -> dict[str, object]:
    """Walk the model, fill `walk` with files, and return the non-file parts."""
    modules = model.get("modules") or {}
    generated = model.get("generated") or {}
    packages = model.get("packages") or {}
    options = parse_build_args(args, model.get("options") or [], walk)
    target_text = (options.get("target") if isinstance(options.get("target"), str) else None)

    for name in REFUSED_ENV:
        if env.get(name):
            walk.refuse(f"environment variable {name} is set and redirects the compiler, libc or SDK")

    # Module sources and native inputs.
    roots: list[Path] = []
    for name, module in sorted(modules.items()):
        for field_name in ("pre", "post"):
            if module.get(field_name):
                walk.refuse(
                    f"module {name!r} has {field_name} commands, which run arbitrary programs "
                    "with inputs the key cannot see"
                )
        roots.append(project / module["root"])
        for install in module.get("install_dirs", []):
            walk.add_tree("installs", project / install["source_dir"], f"module {name!r} install directory")
        native = module.get("native") or {}
        include_dirs = [project / d for d in native.get("include_dirs", [])]
        for directory in native.get("include_dirs", []):
            walk.add_tree("headers", project / directory, f"module {name!r} include directory")
        for directory in native.get("system_include_dirs", []):
            if inside(directory):
                walk.add_tree("headers", project / directory, f"module {name!r} system include directory")
            else:
                walk.refuse(f"module {name!r} searches {directory}, a system directory the key cannot hash")
        for directory in native.get("library_paths", []):
            if inside(directory):
                walk.add_tree("objects", project / directory, f"module {name!r} library directory")
            else:
                walk.refuse(f"module {name!r} searches {directory}, a system directory the key cannot hash")
        for source in native.get("c_sources", []):
            walk_c(walk, project / source, include_dirs)
        for obj in native.get("object_files", []):
            walk.add("objects", project / obj, f"module {name!r} object file")
        for field_name in ("system_libs", "pkg_config_libs", "frameworks"):
            for lib in native.get(field_name, []):
                walk.refuse(f"module {name!r} links {field_name} entry {lib!r}, whose contents are a host input")
        if native.get("link_libc") or native.get("link_libcpp"):
            if not explicit_abi_target(target_text):
                walk.refuse(
                    f"module {name!r} links libc; pass -Dtarget=<arch>-<os>-<abi> with an explicit "
                    "non-Apple ABI so the libc is the one Zig bundles"
                )

    # Generators.
    for name, gen in sorted(generated.items()):
        if gen.get("command"):
            scan_command(walk, name, gen, project)
        tool = gen.get("tool")
        if isinstance(tool, dict):
            reached = walk_zig(walk, [project / tool["root"]], f"generated step {name!r} tool source", "generated")
            scan_tool(walk, name, reached)
        for arg in gen.get("args", []):
            if arg.get("kind") == "input_file":
                path = project / arg["value"]
                if path.is_dir():
                    walk.add_tree("generated", path, f"generated step {name!r} input")
                elif path.suffix == ".zig":
                    walk_zig(walk, [path], f"generated step {name!r} input", "generated")
                else:
                    walk.add("generated", path, f"generated step {name!r} input")
        if gen.get("stdin"):
            walk.add("generated", project / gen["stdin"], f"generated step {name!r} stdin")
    for name, module in sorted(modules.items()):
        for use in module.get("gen_imports", []):
            reached = walk_zig(walk, [project / use["tool_root"]], f"module {name!r} generator tool", "generated")
            scan_tool(walk, f"{name}:{use['alias']}", reached)
            for arg in use.get("args", []):
                if arg.get("kind") == "input_file":
                    walk.add("generated", project / arg["value"], f"module {name!r} generator input")

    walk_zig(walk, roots, "module source")

    # Packages.
    package_ids: dict[str, object] = {}
    for alias, package in sorted(packages.items()):
        if package.get("path"):
            walk.add_tree("packages", project / package["path"], f"package {alias!r} path")
            package_ids[alias] = {"path": package["path"], "lazy": package.get("lazy", False)}
        elif package.get("url") and package.get("hash"):
            package_ids[alias] = {"url": package["url"], "hash": package["hash"], "lazy": package.get("lazy", False)}
        else:
            walk.refuse(f"package {alias!r} has neither a path nor a url with a hash")

    # System dependencies.
    system: list[dict[str, str]] = []
    for dep in model.get("system_deps") or []:
        if dep.get("kind") != "tool":
            walk.refuse(
                f"system dependency {dep.get('name')!r} ({dep.get('kind')}) is a host input; "
                "only `tool` dependencies, which the build runs but does not link, can be cached"
            )
        system.append({"name": dep.get("name", ""), "kind": dep.get("kind", "")})

    return {"options": options, "packages": package_ids, "system": sorted(system, key=lambda d: (d["kind"], d["name"]))}


def compute(
    project: Path,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    zig: str | None = None,
    model: dict | None = None,
) -> Closure:
    """Walk the declared inputs of `project` for `zig build <args>`."""
    project = project.resolve()
    args = list(args or [])
    env = dict(os.environ if env is None else env)
    hasher = Hasher(project)
    walk = Walk(hasher, {}, [])
    if model is None:
        model = export_model(project)

    extra = collect(project, model, args, env, walk)

    # Engine: the project's copies of the pipeline files and this closure's code.
    azazel_root = Path(__file__).resolve().parents[1]
    for name in ENGINE_FILES:
        for base in (project, azazel_root):
            if (base / name).is_file():
                walk.add("engine", base / name, "engine file")
                break
    for tool in ("cache_closure.py", "zig_toolchain.py"):
        walk.add("engine", Path(__file__).resolve().parent / tool, "engine file")

    toolchain = zig_identity(zig, walk.refusals)
    lanes = (model.get("toolchain") or {}).get("zig", {}).get("lanes") or []
    if toolchain and lanes:
        try:
            lane = zig_toolchain.ZigVersion.parse(toolchain["version"]).lane
        except zig_toolchain.VersionError:
            lane = ""
        if lane not in lanes:
            walk.refuse(f"zig {toolchain['version']} is outside the declared lanes {lanes}")

    options = extra["options"]
    target = {
        "target": options.get("target"),
        "cpu": options.get("cpu"),
        "dynamic-linker": options.get("dynamic-linker"),
        "native": native_target(zig) if not options.get("target") else None,
    }

    parts = {
        "model": digest_json(model),
        "engine": digest_json({"files": walk.files.get("engine", {}), "cue": cue_version(), "key_version": KEY_VERSION}),
        "toolchain": digest_json(toolchain),
        "target": digest_json(target),
        "options": digest_json(options),
        "sources": digest_json(walk.files.get("sources", {})),
        "headers": digest_json(walk.files.get("headers", {})),
        "objects": digest_json(walk.files.get("objects", {})),
        "installs": digest_json(walk.files.get("installs", {})),
        "generated": digest_json(walk.files.get("generated", {})),
        "packages": digest_json({"ids": extra["packages"], "trees": walk.files.get("packages", {})}),
        "system": digest_json(extra["system"]),
    }
    key = None if walk.refusals else digest_json({"version": KEY_VERSION, "parts": parts})
    return Closure(key=key, parts=parts, files=walk.files, refusals=walk.refusals)


def main(argv: list[str]) -> int:
    project = Path.cwd()
    explain = False
    rest = list(argv)
    command = rest.pop(0) if rest and rest[0] in {"key", "explain"} else "key"
    explain = command == "explain"
    while rest and rest[0] != "--":
        flag = rest.pop(0)
        if flag == "--project" and rest:
            project = Path(rest.pop(0))
        else:
            print(f"error: unknown argument: {flag}", file=sys.stderr)
            return 2
    if rest and rest[0] == "--":
        rest.pop(0)
    try:
        closure = compute(project, rest)
    except ClosureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if explain:
        print(json.dumps(closure.manifest(), indent=2, sort_keys=True))
    if closure.refusals:
        print("azazel: this build is not cacheable:", file=sys.stderr)
        for reason in closure.refusals:
            print(f"  - {reason}", file=sys.stderr)
        return 3
    if not explain:
        print(closure.key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
