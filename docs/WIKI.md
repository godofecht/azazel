# Azazel

Azazel is a deterministic build-model layer for Zig. Projects declare build
intent in CUE, CUE validates and resolves that model, Azazel emits typed Zig
build data, and `std.Build` remains the executor.

The production-supported core is deliberately narrower than every experiment in
this repository. See [`PRODUCTION.md`](PRODUCTION.md) for the exact support
contract and release gate.

---

## Contents

- [The problem](#the-problem)
- [The pipeline](#the-pipeline)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quickstart](#quickstart-5-minutes)
- [Schema reference](#schema-reference)
- [`export.cue`](#exportcue)
- [From build_spec.zig to build.zig](#from-build_speczig-to-buildzig)
- [Examples](#examples)
- [Editor support](#editor-support)
- [Huge project corpus](#huge-project-corpus)
- [Troubleshooting](#troubleshooting)
- [File reference](#file-reference)
- [Links](#links)

---

## The problem

Zig deliberately makes its build system programmable: `build.zig` constructs a
build graph using Zig itself. That is powerful, but project configuration and
`std.Build` compatibility logic can become entangled. When the build API moves
between Zig releases, each project that hand-maintains the same wiring has to
absorb that change independently.

Azazel separates **project intent** from **build execution**.

`project.cue` says what the project contains. `schema.cue` defines the accepted
shape and defaults. `export.cue` turns project declarations into one resolved
build model. `gen_build_spec.sh` converts that model into typed Zig data.
`build.zig` maps the data onto the supported `std.Build` APIs for the active Zig
lane.

This gives the build graph a machine-readable representation before compilation.
It can be validated, inspected, diffed, consumed by editor tooling, replayed
across supported Zig versions, and pressure-tested against real repositories.

Azazel is not intended to replace Zig as the build executor. It is a stable
configuration/IR layer over it.

---

## The pipeline

```text
project.cue
    |
    v
schema.cue + export.cue
    |
    | cue export -e build
    v
resolved build model
    |
    | gen_build_spec.sh
    v
build_spec.zig
    |
    | imported at comptime
    v
build.zig / std.Build
    |
    v
zig-out/
```

The canonical user-facing path is:

```sh
python3 azazel check
python3 azazel gen
python3 azazel build
zig build test --summary all
```

`azazel gen` delegates to `gen_build_spec.sh`. There is only one CUE-to-Zig
generator implementation.

`build_spec.zig` is generated and gitignored. Code generation is memoized using
`.build_spec.stamp`; if the CUE inputs and generator have not changed, an
unchanged regeneration can return immediately. CI deletes the stamp before its
second generation so the determinism test exercises a real second emission.

The generated build spec is Zig source. Runtime build execution does not parse a
JSON configuration file.

---

## Prerequisites

The production release lanes are:

| Tool | Supported production versions |
|---|---|
| Zig | 0.14.1, 0.15.2, 0.16.0 |
| CUE | v0.16.0 in CI |
| Python | Python 3 |

The schema can describe a Zig 0.17 lane for corpus/development work, but 0.17 is
not part of the stable production matrix while that toolchain is moving.

On macOS, Zig 0.16.0 is the hosted-CI smoke lane. Zig 0.15.2 remains covered in
Linux CI; the current GitHub macOS 26 arm64 image cannot link the Zig 0.15.2
build runner, so Azazel does not advertise that combination as a supported
macOS guarantee.

---

## Installation

For the repository itself:

```sh
git clone https://github.com/godofecht/azazel.git
cd azazel
./setup.sh --check-only
python3 azazel check
python3 azazel build
```

`setup.sh` verifies Zig, CUE, and Python, generates the build spec, builds the
repository fixture, and runs its tests. `--examples` additionally exercises the
self-contained examples.

Azazel is pre-1.0. A production consumer should pin the exact revision or
release used by CI and upgrade deliberately. The current repository still
supports a vendored/copy-oriented integration shape; replacing that with a
centrally versioned consumer dependency is tracked as production-adoption work.

---

## Quickstart (5 minutes)

Start with one import-only module and one executable:

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

Expose both declarations from `export.cue`:

```cue
_modules: {
    "core": core
    "app":  app
}
```

Validate and build:

```sh
python3 azazel check
python3 azazel gen
python3 azazel build
```

Inspect the fully resolved model at any point:

```sh
python3 azazel info
```

Normal Zig build arguments are forwarded by `azazel build`:

```sh
python3 azazel build -Dfeature=true
```

A module declared in `project.cue` but omitted from `_modules` is intentionally
outside the exported graph. Keep `_modules` as the explicit list of targets the
model exposes.

---

## Schema reference

The authoritative schema is [`../schema.cue`](../schema.cue). This section
explains the current production-facing model; use the schema itself when exact
field types matter.

### `#Module`

| Field | Purpose | Default |
|---|---|---|
| `kind` | `exe`, `static`, `shared`, or `module` | required |
| `root` | root Zig source file | required |
| `artifact_name` | produced artifact name independent of graph/import key | module key |
| `deps` | internal module dependencies | `[]` |
| `profile` | `debug` or `release` | `debug` |
| `link` | dependency consumption mode: `abi` or `import` | `abi` |
| `pre` | commands that must run before a compile artifact | `[]` |
| `post` | commands that run after installation | `[]` |
| `install_dirs` | directories/resources to stage during install | `[]` |
| `pkg_library_paths` | library search paths supplied by package dependencies | `[]` |
| `pkg_imports` | modules imported from Zig package dependencies | `[]` |
| `pkg_artifacts` | native/build artifacts linked from package dependencies | `[]` |
| `build_options` | named CLI options exposed to a module | `[]` |
| `option_values` | fixed typed values injected into an options module | `[]` |
| `gen_imports` | Zig modules produced by declared host tools | `[]` |
| `build_options_import` | import name for the generated options module | `build-options` |
| `native` | C/C++ sources, include paths, objects, libraries, frameworks | `{}` |

A `shared` target is always an ABI artifact. A `module` target is always consumed
through import mode and produces no standalone artifact.

### `kind`

`exe` creates an executable. `static` creates a static library when linked over
an ABI edge, or can be consumed as a Zig import when `link: "import"` is used.
`shared` creates a dynamic/shared library and is always ABI-linked. `module` is a
named Zig module that exists only for `@import` consumption.

### `artifact_name`

The CUE field key is the build-graph and `@import` name. `artifact_name` lets the
produced file use a different name:

```cue
xev_c_api: #Module & {
    kind:          "static"
    root:          "src/c_api.zig"
    artifact_name: "xev"
}
```

This is necessary for projects where an import module and an ABI artifact share
an upstream product name.

### `deps` and `link`

`deps` refers to other exported Azazel modules.

With `link: "import"`, a dependency is attached with `Module.addImport` and
compiles inside its consumer. This is the normal shape for pure Zig module
relationships.

With `link: "abi"`, the dependency has its own compile artifact and the consumer
links it. This is required for shared libraries and useful for explicit binary
boundaries or C/C++ interoperability.

Large projects can combine both into **clusters**: many import-connected Zig
modules inside a cluster, with ABI artifacts between clusters. See
[`../examples/06-clusters`](../examples/06-clusters/).

### Profiles

`debug` resolves to Zig `Debug`; `release` resolves to `ReleaseFast`. The
resolved optimization mode is written into `build_spec.zig`, so the executor
receives a typed `std.builtin.OptimizeMode`.

### Toolchain lanes

A project can narrow the Zig lanes accepted by the generated build:

```cue
toolchain: zig: {
    lanes: ["0.15", "0.16"]
    preferred: "0.16"
}
```

The executor checks the current Zig minor version before doing real build work
and emits a compile error if it falls outside the declared lanes.

### Native sources and libraries

`native` can model C sources, include and system-include directories, library
paths, object files, system libraries, pkg-config libraries, Apple frameworks,
and libc/libc++ linkage.

```cue
native: {
    c_sources: ["src/native.c"]
    include_dirs: ["include"]
    system_libs: ["sqlite3"]
    frameworks: ["CoreFoundation"]
    link_libc: true
}
```

Platform/system availability is still an external property. Corpus tooling can
diagnose many missing system dependencies, while first-class project-level
preflight modeling remains an active roadmap item.

### Build options

Top-level `options` declare user-selectable typed values (`bool`, `string`, or
`u32`). A module names the options it consumes through `build_options`.

`option_values` supplies fixed values that an upstream project would otherwise
synthesize in `build.zig`, including boolean, string, `u32`, and optional
40-character commit values. These are emitted into the same options module and
made available under `build_options_import`.

### Package imports and artifacts

`pkg_imports` consumes modules exported by `build.zig.zon` dependencies.
`pkg_artifacts` links artifacts exported by those dependencies.
`pkg_library_paths` adds package-provided library search paths with optional OS
and architecture filters.

The current model can forward target/optimization settings and supports the
real-project package option shapes already exercised by the corpus, including a
backend enum and string-list fields. Those package-specific option forms are a
known transitional limitation; the roadmap is to replace them with one generic
typed dependency-argument representation rather than adding more special cases.

### Generated imports

`gen_imports` models a common Zig build pattern: compile a host tool, run it,
and import the generated Zig file into another module.

Each generated import declares the tool source/name, ordered arguments, and the
output file that becomes the generated module root. Arguments can be literals,
input files, or output files. Input/output paths participate in Zig's build
graph through `LazyPath` rather than being treated as opaque post-processing.

### `pre` and `post`

Commands are represented as explicit argv arrays rather than shell strings:

```cue
pre: [{ argv: ["python3", "tools/generate.py"] }]
```

These commands are supported by the build executor, but they are one reason the
experimental whole-build remote cache is not yet production-safe: arbitrary
commands can read undeclared files or environment variables.

---

## `export.cue`

`project.cue` contains declarations. `export.cue` defines which declarations
become the resolved build graph and normalizes the module fields used by code
generation.

The root `_modules` map is the explicit export list. For every exported module,
`export.cue` currently carries the complete executor contract, including
`option_values` and `gen_imports`. The canonical CLI verifies that no required
module field disappeared during export.

That check exists because a schema feature is not implemented merely because a
field parses: it must survive schema validation, export, Zig code generation,
and execution.

---

## From build_spec.zig to build.zig

`build_spec.zig` contains typed constants describing toolchain lanes, packages,
options, and modules. `build.zig` imports it at comptime.

The executor first rejects unsupported Zig lanes. It then creates a
`std.Build.Module` for each declared module, applies native metadata and build
options, wires package imports/artifacts and generated modules, creates compile
artifacts only for targets that need them, connects import or ABI dependency
edges, and attaches installation/post-build steps.

Module-only targets and import-mode static targets do not need an independent
compile artifact. ABI static libraries, shared libraries, and executables do.

The compatibility code is intentionally centralized here. Consumers should not
need to reproduce every `std.Build` API spelling change in project
configuration.

---

## Examples

The repository contains self-contained build examples under `examples/`.

`01-hello` is the minimum project. `02-lib-and-app` demonstrates a library plus
an executable. `03-services` uses multiple artifact kinds and dependency edges.
`04-validation` demonstrates rejected configurations. `05-import-mode` shows a
pure Zig import edge. `06-clusters` combines import-connected internals with ABI
boundaries for large graphs.

Run all maintained examples from the repository root with:

```sh
./setup.sh --examples
```

Danzig examples are dogfood/integration workloads, not part of the Azazel
build-system API. Their extraction into a standalone consumer project is tracked
separately.

---

## Editor support

`ide/` contains VS Code and language-server tooling for authoring Azazel CUE
models. The tooling can surface CUE diagnostics and provide completion, hover,
and definition assistance for model fields and dependency names.

Editor support is useful, but it is currently outside the production build
contract: a normal Azazel build must not depend on an editor extension or LSP.

---

## Huge project corpus

`tools/huge_corpus.py` pressure-tests the model against substantial Zig
repositories including ZLS, libxev, River, Mach, MicroZig, libvaxis, Capy,
zig-gamedev, TigerBeetle, and Ghostty.

The corpus separates several facts that must not be conflated:

An **upstream build result** says whether the project's own `build.zig` works in
a controlled environment. An **Azazel executable parity result** says a modeled
target slice compiled through the Azazel-generated build graph. A project can
have one without the other.

Current corpus work has exercised real import modules, package dependencies,
native package artifacts, package library paths, generated source modules,
fixed build-option modules, and resource staging. It does not claim that every
full upstream build graph has been replaced.

See [`HUGE_PROJECT_CORPUS.md`](HUGE_PROJECT_CORPUS.md) for the detailed matrix.
Corpus automation itself is validation/research infrastructure rather than a
runtime dependency of Azazel builds.

---

## Troubleshooting

### `azazel check` reports missing exported fields

A field exists in the schema or project declaration but was not preserved by
`export.cue`. Treat this as an Azazel pipeline bug, not as a compiler failure.
Every field consumed by the generator must be present in the resolved module
object.

### Unknown dependency

Every value in `deps` must name a module present in the exported `_modules` map.
`azazel check` rejects unknown and self dependencies and detects cycles before
code generation.

### Unsupported Zig lane

The generated spec contains the project's accepted minor-version lanes. Use a
matching Zig version or change the project toolchain declaration only after the
project has actually been tested on that lane.

### CUE accepts a module but it is not built

Check `_modules` in `export.cue`. Only explicitly exported declarations become
part of the model.

### Package dependency panics on an option

A package may expose a build-option surface Azazel does not model yet. Do not
paper over that by silently dropping the option. Add an explicit modeled shape
and real-project test, or wait for the generic typed dependency-argument work.

### Shared cache refuses to run

That is intentional. `cache_build.sh` requires
`AZAZEL_EXPERIMENTAL_CACHE=1`. The current key does not prove a complete input
closure, so the shared cache is not suitable for release artifacts. Read
[`../CACHE.md`](../CACHE.md) before experimenting with it.

### macOS Zig 0.15.2 fails before project compilation

On the current GitHub-hosted macOS 26 arm64 image, Zig 0.15.2 cannot link its
build runner against the host platform symbols. Azazel's stable 0.15.2 lane is
therefore verified on Linux; the macOS production smoke lane uses Zig 0.16.0.

---

## File reference

| Path | Role | Production status |
|---|---|---|
| `project.cue` | project declarations | core |
| `schema.cue` | CUE types/defaults/constraints | core |
| `export.cue` | resolved build-model projection | core |
| `gen_build_spec.sh` | canonical CUE-to-Zig code generator | core |
| `build_spec.zig` | generated typed build IR | generated core |
| `build.zig` | Zig executor/compatibility layer | core |
| `azazel` | canonical CLI/orchestrator and preflight checks | core |
| `build_spec_test.zig` | resolved-spec invariants | core tests |
| `compat.zig` | supported Zig-version compatibility helpers | core |
| `setup.sh` | repository/bootstrap verification | supported helper |
| `docs/PRODUCTION.md` | support and release contract | policy |
| `tools/huge_corpus.py` | real-project pressure testing | experimental/validation |
| `cache_key.sh` | whole-build cache-key prototype | experimental |
| `cache_build.sh` | shared artifact cache prototype | experimental, gated |
| `ide/` | editor/LSP tooling | experimental tooling |
| `src/danzig/` | VST3 dogfood workload | not Azazel API |

---

## Links

The repository is <https://github.com/godofecht/azazel>.

Production guarantees are defined in [`PRODUCTION.md`](PRODUCTION.md).
Contribution requirements are in [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
Security reporting guidance is in [`../SECURITY.md`](../SECURITY.md).
The experimental cache status is documented in [`../CACHE.md`](../CACHE.md).

Azazel is also the declarative configuration frontend for
[Zaza](https://github.com/godofecht/zaza).