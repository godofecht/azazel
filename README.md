# Azazel

[![CI](https://github.com/godofecht/azazel/actions/workflows/ci.yml/badge.svg)](https://github.com/godofecht/azazel/actions/workflows/ci.yml)
[![Zig](https://img.shields.io/badge/zig-0.14.1%20%7C%200.15.2%20%7C%200.16.0-f7a41d)](https://ziglang.org/)

A deterministic build configuration layer powered by **CUE** for constraint validation and **Zig** for execution. The configuration frontend for [Zaza](https://github.com/godofecht/zaza).

```
project.cue  →  CUE validates  →  build_spec.zig  →  zig build  →  binary
  (human)        (schema.cue)      (generated)        (engine)
```

No JSON runtime. No flags. No ceremony.

## What It Looks Like

```cue
package build

core: #Module & {
    kind: "module"
    root: "src/core.zig"
}

app: #Module & {
    kind:    "exe"
    root:    "src/main.zig"
    deps:    ["core"]
    profile: "release"
}
```

That's the core project configuration. Toolchain lanes, import-mode linking,
and post-build commands are opt-in when a project needs them.

## Quick Start

```sh
brew install cue zig           # prerequisites (also needs python3)
git clone https://github.com/godofecht/azazel.git
cd azazel
./setup.sh                     # check tools, generate, build, test
./zig-out/bin/app              # run
```

`setup.sh` reports the versions of `zig`, `cue` and `python3`, prints install
hints for anything missing, then runs the full pipeline. It uses a
Zig-version-specific cache directory by default, so switching between the
0.14/0.15/0.16 lanes does not reuse a stale build runner. It is safe to run
repeatedly and exits non-zero on the first failure.

```sh
./setup.sh --check-only        # just report tool versions
./setup.sh --examples          # also build and test everything in examples/
ZIG=/path/to/zig ./setup.sh    # use a specific Zig binary
ZIG_CACHE_DIR=/tmp/azazel-cache ./setup.sh
```

Doing it by hand is three commands:

```sh
./gen_build_spec.sh            # CUE validates → generates build_spec.zig
zig build                      # compile
zig build test --summary all   # 56 tests
```

## How It Works

| Layer | Tool | File | Purpose |
|-------|------|------|---------|
| Human | You | `project.cue` | Declare modules, deps, profiles |
| Constraint | CUE | `schema.cue` | Type-check and resolve defaults |
| Codegen | Shell | `gen_build_spec.sh` | Emit typed Zig source (not JSON) |
| Execution | Zig | `build.zig` | Compile and link from spec |

CUE generates **Zig source code**, not JSON. The build system never parses anything at runtime. The module array is a compile-time constant.

## Module Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `kind` | `"exe"` \| `"static"` \| `"shared"` \| `"module"` | Yes | — | Output type |
| `root` | `string` | Yes | — | Root source file |
| `deps` | `[...string]` | No | `[]` | Module dependencies |
| `profile` | `"debug"` \| `"release"` | No | `"debug"` | Optimization level |
| `link` | `"abi"` \| `"import"` | No | `"abi"` | How dependents consume this module |
| `pre` | `[{ argv: [...] }]` | No | `[]` | Commands to run before compiling this module |
| `post` | `[{ argv: [...] }]` | No | `[]` | Commands to run after installing this module |
| `pkg_imports` | package import list | No | `[]` | Imports from `build.zig.zon` dependencies |
| `build_options` | `[...string]` | No | `[]` | Typed options to expose through an options module |
| `native` | native metadata | No | `{}` | C sources, include dirs, system libs, frameworks |

`project.cue` can also declare the supported Zig toolchain lanes:

```cue
toolchain: zig: {
    lanes: ["0.14", "0.15", "0.16"]
    preferred: "0.15"
}
```

Azazel intentionally tracks Zig by minor-version lanes because `std.Build`
changes between Zig releases. The generated `build_spec.zig` records those
lanes and `build.zig` rejects unsupported lanes before doing any real work.

Two things that catch people out. Every module also has to be listed in
`export.cue`'s `_modules` map, or it is silently not built. And by default `deps`
is a linker edge, so symbols cross it as `pub export fn` / `extern fn` rather
than as a Zig `@import`. Both are covered in
[docs/WIKI.md](docs/WIKI.md#deps).

Set `link: "import"` on a dependency to consume it as a Zig module instead. It
merges into its dependents (`@import("name")`) as one compilation, with no
separate artifact and no link step. That rebuilds much faster on pure
Zig-to-Zig graphs. Keep the default `"abi"` for shared libraries and C or C++
interop. See [`link`](docs/WIKI.md#link) and
[`examples/05-import-mode`](examples/05-import-mode/).

For large Zig projects, prefer `kind: "module"` for named modules that should
never produce an artifact. A `module` target is always consumed by import.

Large projects can also declare package imports and native link metadata:

```cue
options: [{
    name: "enable_tracy"
    type: "bool"
    description: "Enable Tracy instrumentation"
    default: false
}]

app: #Module & {
    kind: "exe"
    root: "src/main.zig"
    build_options: ["enable_tracy"]
    pkg_imports: [{
        alias: "known-folders"
        package: "known_folders"
        module: "known-folders"
    }]
    native: {
        link_libc: true
        system_libs: ["sqlite3"]
        pkg_config_libs: ["libinput"]
        frameworks: ["CoreFoundation"]
    }
}
```

## Examples

Four runnable projects, each self-contained with its own README.

| Directory | Demonstrates |
|-----------|--------------|
| [`examples/01-hello`](examples/01-hello/) | The minimum module. Both schema defaults. |
| [`examples/02-lib-and-app`](examples/02-lib-and-app/) | `deps`, `profile`, static linkage, the C-ABI boundary. |
| [`examples/03-services`](examples/03-services/) | All three kinds, a shared library, multiple deps, mixed profiles. |
| [`examples/04-validation`](examples/04-validation/) | Every rejection the schema performs, with real `cue` output. |
| [`examples/05-import-mode`](examples/05-import-mode/) | `link: "import"`, a dependency merged as a Zig module instead of linked. |
| [`examples/06-clusters`](examples/06-clusters/) | Clusters: `import` graphs behind `abi` boundaries, the shape for large projects. |

```sh
cd examples/03-services
./gen_build_spec.sh && zig build && ./zig-out/bin/gateway
```

## Documentation

**[docs/WIKI.md](docs/WIKI.md)** is the complete reference: the pipeline, every
schema field with a worked example, how `build_spec.zig` maps onto
`build.zig`, and troubleshooting for the common failures.

Published at [godofecht.github.io/azazel](https://godofecht.github.io/azazel/),
regenerated from [docs/WIKI.md](docs/WIKI.md) on every change.

- [Huge Zig Project Corpus](docs/HUGE_PROJECT_CORPUS.md)
- [The Pipeline](https://godofecht.github.io/azazel/pipeline.html)
- [Installation](https://godofecht.github.io/azazel/installation.html)
- [Quickstart](https://godofecht.github.io/azazel/quickstart.html)
- [Schema Reference](https://godofecht.github.io/azazel/schema-reference.html)
- [Code Generation](https://godofecht.github.io/azazel/code-generation.html)
- [Examples](https://godofecht.github.io/azazel/examples.html)
- [Troubleshooting](https://godofecht.github.io/azazel/troubleshooting.html)

The corpus runner also has an executable parity lane:
`tools/huge_corpus.py --executable-parity` regenerates Azazel's build spec in a
repo-local `.azazel/parity-work/` workspace and runs modeled target slices
against upstream source. The ready slices cover the `libxev` module probe,
`libvaxis` package-backed module probe, and `zig-gamedev` shared vectormath
module plus pinned `zmath`/`zopengl`/`zglfw` package probe. `zig-gamedev` also
links `zglfw`'s exported `glfw` artifact through the generated parity
workspace. `libvaxis` resolves local `zigimg` and `uucode` path dependencies
through the generated parity workspace.
Use `tools/huge_corpus.py --plan --expect-count 10` before a full batch run to
write `corpus-plan.json` and verify that all ten tracked forks are selected.
Use `tools/huge_corpus.py --roadmap --expect-count 10` to generate
`corpus-roadmap.md` plus issue-ready markdown files under `corpus-issues/` from
the same manifest data.
Future entries can stay marked `unverified` until their real baseline command
has been run and classified.

## Editor support

[`ide/`](ide/) has a VS Code extension for authoring `project.cue`: syntax
highlighting for the `#Module` fields, inline diagnostics that run
`cue export -e build` on save, graph warnings for missing dependency targets and
unexported modules, completion for fields and enum values, hover help, and
go-to-definition from `deps` strings to module declarations. It also adds an
"Azazel: Generate build_spec" command. Open `ide/vscode` in VS Code and press F5
to try it; see [`ide/vscode/README.md`](ide/vscode/README.md).

A dependency-free stdio language server with the same diagnostics, completion,
hover, and definition behavior lives in [`ide/server`](ide/server/); see
[`ide/DESIGN.md`](ide/DESIGN.md).

## Install

Azazel ships a `build.zig.zon`, so it is fetchable with the Zig package manager:

```sh
zig fetch --save git+https://github.com/godofecht/azazel
```

Most projects use it as a starting point rather than a linked dependency: copy a
directory from `examples/` (or the repo root) and edit `project.cue`. The
maintained Zig lanes are 0.14.x, 0.15.x, and 0.16.x; project configs can narrow
that list with `toolchain.zig.lanes`.

## Part of the Zaza Ecosystem

Azazel is the declarative configuration frontend for [Zaza](https://github.com/godofecht/zaza), a Zig-driven build system for C, C++, Zig, CMake-interop, and WebAssembly. Azazel can also be used standalone with any Zig project.

## License

MIT
