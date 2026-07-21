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
brew install cue zig           # prerequisites
git clone https://github.com/godofecht/azazel.git
cd azazel
./gen_build_spec.sh            # CUE validates → generates build_spec.zig
zig build                      # compile
./zig-out/bin/app              # run
```

## How It Works

| Layer | Tool | File | Purpose |
|-------|------|------|---------|
| Human | You | `project.cue` | Declare modules, deps, profiles |
| Constraint | CUE | `schema.cue` | Type-check and resolve defaults |
| Codegen | Shell | `gen_build_spec.sh` | Emit typed Zig source (not JSON) |
| Execution | Zig | `build.zig` | Compile and link from spec |

CUE generates **Zig source code**, not JSON. The build system never parses anything at runtime — the module array is a compile-time constant.

## Module Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `kind` | `"exe"` \| `"static"` \| `"shared"` | Yes | — | Output type |
| `root` | `string` | Yes | — | Root source file |
| `deps` | `[...string]` | No | `[]` | Module dependencies |
| `profile` | `"debug"` \| `"release"` | No | `"debug"` | Optimization level |

## Documentation

Full docs at [abhishek-shivakumar.com/azazel](https://abhishek-shivakumar.com/azazel/)

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
