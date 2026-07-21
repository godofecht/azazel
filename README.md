# Azazel

[![CI](https://github.com/godofecht/azazel/actions/workflows/ci.yml/badge.svg)](https://github.com/godofecht/azazel/actions/workflows/ci.yml)
[![Zig](https://img.shields.io/badge/zig-0.14.1%20%7C%200.15.2-f7a41d)](https://ziglang.org/)

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
    kind: "static"
    root: "src/core.zig"
}

app: #Module & {
    kind:    "exe"
    root:    "src/main.zig"
    deps:    ["core"]
    profile: "release"
}
```

That's the entire project configuration. Two modules, four fields each.

## Quick Start

```sh
brew install cue zig           # prerequisites (also needs python3)
git clone https://github.com/godofecht/azazel.git
cd azazel
./setup.sh                     # check tools, generate, build, test
./zig-out/bin/app              # run
```

`setup.sh` reports the versions of `zig`, `cue` and `python3`, prints install
hints for anything missing, then runs the full pipeline. It is safe to run
repeatedly and exits non-zero on the first failure.

```sh
./setup.sh --check-only        # just report tool versions
./setup.sh --examples          # also build and test everything in examples/
ZIG=/path/to/zig ./setup.sh    # use a specific Zig binary
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
| `kind` | `"exe"` \| `"static"` \| `"shared"` | Yes | — | Output type |
| `root` | `string` | Yes | — | Root source file |
| `deps` | `[...string]` | No | `[]` | Module dependencies |
| `profile` | `"debug"` \| `"release"` | No | `"debug"` | Optimization level |

Two things that catch people out. Every module also has to be listed in
`export.cue`'s `_modules` map, or it is silently not built. And `deps` is a
linker edge, so symbols cross it as `pub export fn` / `extern fn` rather than
as a Zig `@import`. Both are covered in
[docs/WIKI.md](docs/WIKI.md#deps).

## Examples

Four runnable projects, each self-contained with its own README.

| Directory | Demonstrates |
|-----------|--------------|
| [`examples/01-hello`](examples/01-hello/) | The minimum module. Both schema defaults. |
| [`examples/02-lib-and-app`](examples/02-lib-and-app/) | `deps`, `profile`, static linkage, the C-ABI boundary. |
| [`examples/03-services`](examples/03-services/) | All three kinds, a shared library, multiple deps, mixed profiles. |
| [`examples/04-validation`](examples/04-validation/) | Every rejection the schema performs, with real `cue` output. |

```sh
cd examples/03-services
./gen_build_spec.sh && zig build && ./zig-out/bin/gateway
```

## Documentation

**[docs/WIKI.md](docs/WIKI.md)** is the complete reference: the pipeline, every
schema field with a worked example, how `build_spec.zig` maps onto
`build.zig`, and troubleshooting for the common failures.

Also published at [abhishek-shivakumar.com/azazel](https://abhishek-shivakumar.com/azazel/)

- [Getting Started](https://abhishek-shivakumar.com/azazel/getting-started.html)
- [Project File](https://abhishek-shivakumar.com/azazel/project-file.html)
- [Schema Reference](https://abhishek-shivakumar.com/azazel/schema-reference.html)
- [Examples](https://abhishek-shivakumar.com/azazel/examples.html)
- [Code Generation](https://abhishek-shivakumar.com/azazel/code-generation.html)
- [Architecture](https://abhishek-shivakumar.com/azazel/architecture.html)

## Part of the Zaza Ecosystem

Azazel is the declarative configuration frontend for [Zaza](https://github.com/godofecht/zaza), a Zig-driven build system for C, C++, Zig, CMake-interop, and WebAssembly. Azazel can also be used standalone with any Zig project.

## License

MIT
