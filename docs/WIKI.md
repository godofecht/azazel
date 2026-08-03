# Azazel

A build configuration layer for Zig. You describe your modules in CUE. CUE
type-checks them and fills in defaults. A shell script turns the result into a
Zig source file. `build.zig` walks that file and produces the compile graph.

Source: <https://github.com/godofecht/azazel>

---

## Contents

- [The problem](#the-problem)
- [The pipeline](#the-pipeline)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quickstart](#quickstart-5-minutes)
- [Schema reference](#schema-reference)
  - [`#Module`](#module)
  - [`kind`](#kind)
  - [`root`](#root)
  - [`deps`](#deps)
  - [`link`](#link)
  - [`profile`](#profile)
  - [`#Kind`](#kind-1)
  - [`#Profile` and `#Profiles`](#profile-and-profiles)
- [`export.cue`](#exportcue)
- [From build_spec.zig to build.zig](#from-build_speczig-to-buildzig)
- [Examples](#examples)
- [Editor support](#editor-support)
- [Huge project corpus](#huge-project-corpus)
- [Troubleshooting](#troubleshooting)
- [File reference](#file-reference)

---

## The problem

A `build.zig` starts as twenty lines and ends as four hundred. Module wiring,
optimization modes, link edges and install rules all live in imperative code,
mixed with real logic. Adding a library means editing that code. Answering
"what does this project build, and how" means reading it.

Azazel splits the description from the execution.

`project.cue` holds the description. It is data, so a schema can validate it.
A typo in a `kind`, a wrong type on a field, an unrecognised option: these are
rejected by `cue` before any Zig runs, with a message pointing at the line.

`build.zig` holds the execution. It is a fixed loop, about forty lines, and it
does not change when your project does.

The generated file in between is Zig source, so there is no parser and no JSON
at build time. The module list is a compile-time constant.

The surface is deliberately small. Modules describe their artifact shape,
source root, dependency edges, link mode, profile, and optional post-build
commands. There are still no arbitrary compiler flags, include paths, platform
triples, or linker options. `#Module` is a closed CUE definition, so there is no
escape hatch either:

```
$ cue export -e build
app.flags: field not allowed:
    ./project.cue:8:2
```

If you need something outside those four fields, `build.zig` is still an
ordinary `build.zig` and you can add it there.

---

## The pipeline

```
project.cue  ->  cue export  ->  build_spec.zig  ->  zig build  ->  binaries
   (you)         (validates)      (generated)        (executes)     (zig-out/)
     |                |
  schema.cue     export.cue
  (types)        (what to emit)
```

Step by step:

1. You edit `project.cue`.
2. `./gen_build_spec.sh` runs `cue export -e build`. CUE unifies your
   declarations with `schema.cue`, resolves defaults, maps each `profile` to
   an optimization mode, and rejects anything invalid.
3. The same script pipes the resolved JSON through `python3` and writes
   `build_spec.zig`, a plain Zig array.
4. `zig build` imports `build_spec.zig` at comptime and walks it.

`build_spec.zig` is gitignored. It is regenerated, never edited.

Run step 2 after every change to `project.cue`, `export.cue` or `schema.cue`.
Nothing watches for you.

---

## Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Zig | 0.14.x, 0.15.x or 0.16.x | supported `std.Build` lanes |
| CUE | v0.16.0 | validates and exports the config |
| Python 3 | any 3.x | `gen_build_spec.sh` uses it to emit Zig from CUE's JSON |

Azazel is maintained by Zig minor-version lane because `std.Build` changes
between releases. Project configs can narrow the supported lanes with
`toolchain.zig.lanes`; the generated `build_spec.zig` records that contract and
`build.zig` rejects an unsupported host lane before compiling modules.

macOS:

```sh
brew install zig cue
```

Linux: get Zig from <https://ziglang.org/download/> and CUE from
<https://cuelang.org/docs/introduction/installation/>, or
`go install cuelang.org/go/cmd/cue@latest`.

Python 3 ships with macOS and every mainstream Linux distribution.

---

## Installation

```sh
git clone https://github.com/godofecht/azazel.git
cd azazel
./setup.sh
```

`setup.sh` checks the toolchain, generates `build_spec.zig`, builds, and runs
the tests. It uses Zig-version-specific cache directories by default, so
switching between the 0.14/0.15/0.16 lanes does not reuse a stale build runner.
It is safe to run repeatedly and exits non-zero on the first failure.

```
$ ./setup.sh

== Checking prerequisites
  zig      0.15.2   (/opt/homebrew/bin/zig)
  cue      v0.16.0   (/opt/homebrew/bin/cue)
  python3  3.9.6   (/usr/bin/python3)

== Generating build_spec.zig
Generated build_spec.zig

== Building

== Testing

Build Summary: 7/7 steps succeeded; 56/56 tests passed
test success
+- run test 12 passed 1ms MaxRSS:1M
|  +- compile test Debug native cached 40ms MaxRSS:34M
+- run test 9 passed 1ms MaxRSS:2M
|  +- compile test Debug native cached 40ms MaxRSS:34M
+- run test 35 passed 1ms MaxRSS:1M
   +- compile test Debug native cached 40ms MaxRSS:34M


Done.

  ./zig-out/bin/app          run the sample executable
  $EDITOR project.cue        declare your modules
  ./gen_build_spec.sh        regenerate after every project.cue change
  docs/WIKI.md               full reference
```

Other invocations:

```sh
./setup.sh --check-only              report tool versions and stop
./setup.sh --examples                also build and test everything in examples/
ZIG=/path/to/zig ./setup.sh          use a specific Zig binary
CUE=/path/to/cue ./setup.sh          use a specific CUE binary
ZIG_CACHE_DIR=/tmp/azazel-cache ./setup.sh
./setup.sh --help
```

If a tool is missing, it says so and points at an installer:

```
$ ZIG=/nonexistent/zig ./setup.sh --check-only

== Checking prerequisites
  zig      MISSING
           macOS:  brew install zig
           Linux:  https://ziglang.org/download/  (or your package manager)
           Any:    https://github.com/marler8997/zigup
           Already installed elsewhere? Run: ZIG=/path/to/zig ./setup.sh
  cue      v0.16.0   (/opt/homebrew/bin/cue)
  python3  3.9.6   (/usr/bin/python3)
error: install the tools above, then run ./setup.sh again
```

---

## Quickstart (5 minutes)

### 1. Build what is already there

```
$ ./gen_build_spec.sh
Generated build_spec.zig

$ zig build

$ ./zig-out/bin/app
azazel
```

### 2. See what CUE resolved

```
$ cue export -e build
{
    "modules": {
        "core": {
            "kind": "static",
            "root": "src/core.zig",
            "deps": [],
            "optimize": "Debug"
        },
        "app": {
            "kind": "exe",
            "root": "src/main.zig",
            "deps": [
                "core"
            ],
            "optimize": "ReleaseFast"
        },
        ...
    }
}
```

`project.cue` never mentions `deps` for `core`, and never mentions
`optimize` at all. CUE supplies `deps: []` from the schema default and turns
`profile: "release"` into `optimize: "ReleaseFast"`.

### 3. Add a module

Append to `project.cue`:

```cue
utils: #Module & {
	kind: "static"
	root: "src/utils.zig"
}
```

Add it to `_modules` in `export.cue`:

```cue
_modules: {
	"core":        core
	"app":         app
	"utils":       utils
	"danzig":      danzig
	"danzig_gain": danzig_gain
	"danzig_test": danzig_test
}
```

Regenerate and build:

```sh
./gen_build_spec.sh && zig build
```

`zig-out/lib/libutils.a` appears.

Forgetting the `export.cue` half is the most common mistake. Nothing errors.
The module is simply not built.

### 4. Depend on it

```cue
app: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	deps:    ["core", "utils"]
	profile: "release"
}
```

`deps` is a linker edge. Symbols cross it as C-ABI symbols. See
[`deps`](#deps) below.

### 5. Run the tests

```
$ zig build test --summary all

Build Summary: 7/7 steps succeeded; 56/56 tests passed
test success
+- run test 12 passed 1ms MaxRSS:1M
|  +- compile test Debug native cached 40ms MaxRSS:34M
+- run test 9 passed 1ms MaxRSS:2M
|  +- compile test Debug native cached 40ms MaxRSS:34M
+- run test 35 passed 1ms MaxRSS:1M
   +- compile test Debug native cached 40ms MaxRSS:34M
```

Available steps:

```
$ zig build --help
Steps:
  install (default)            Copy build artifacts to prefix path
  uninstall                    Remove build artifacts from prefix path
  test                         Run all tests
```

---

## Schema reference

`schema.cue` in full:

```cue
package build

#Kind:    "exe" | "static" | "shared" | "module"
#Profile: "debug" | "release"
#Link:    "abi" | "import"
#ZigLane: "0.14" | "0.15" | "0.16"

#Command: {
	argv: [...string]
}

#Module: {
	kind:     #Kind
	root:     string
	deps: [...string] | *[]
	profile:  #Profile | *"debug"
	link:     #Link | *"abi"
	post: [...#Command] | *[]

	if kind == "shared" {
		link: "abi"
	}

	if kind == "module" {
		link: "import"
	}
}

#Profiles: {
	debug: {
		optimize: "Debug"
	}
	release: {
		optimize: "ReleaseFast"
	}
}

profiles: #Profiles

#Toolchain: {
	zig: {
		lanes: [...#ZigLane] | *["0.14", "0.15", "0.16"]
		preferred: #ZigLane | *"0.15"
	}
}

toolchain: #Toolchain | *{}
```

That is the whole type system. You rarely edit it. Everything below describes
how each part behaves.

### `#Module`

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `kind` | `#Kind` | yes | none |
| `root` | `string` | yes | none |
| `deps` | `[...string]` | no | `[]` |
| `profile` | `#Profile` | no | `"debug"` |
| `link` | `#Link` | no | `"abi"` |
| `pre` | `[...#Command]` | no | `[]` |
| `post` | `[...#Command]` | no | `[]` |
| `pkg_imports` | `[...#PackageImport]` | no | `[]` |
| `pkg_artifacts` | `[...#PackageArtifact]` | no | `[]` |
| `build_options` | `[...string]` | no | `[]` |
| `build_options_import` | `string` | no | `"build-options"` |
| `native` | `#Native` | no | `{}` |

`#Module` is a CUE definition, which makes it closed. Any field not in that
table is rejected.

A module is declared by unifying with it:

```cue
name: #Module & { ... }
```

The CUE field name becomes the module name, which becomes the artifact name.
`core` produces `libcore.a`; `app` produces `app`.

---

### `toolchain`

Optional top-level project contract for the Zig lanes the generated spec
supports:

```cue
toolchain: zig: {
	lanes: ["0.14", "0.15", "0.16"]
	preferred: "0.15"
}
```

Use this when a project or generated `build.zig` intentionally supports only a
subset of Zig's moving `std.Build` API. The generated spec embeds the lanes, and
`build.zig` fails early if the current compiler is outside that list.

---

### `pkg_imports`

Top-level `packages` mirrors package dependency intent for diagnostics and
corpus reporting:

```cue
packages: known_folders: {
	url: "https://example.invalid/known-folders.tar.gz"
	hash: "..."
	lazy: false
}
```

Imports modules from `build.zig.zon` package dependencies:

```cue
app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	pkg_imports: [{
		alias: "known-folders"
		package: "known_folders"
		module: "known-folders"
		pass_target: true
		pass_optimize: true
	}]
}
```

This maps to `b.dependency(package, .{ .target = target, .optimize = optimize })`
followed by `root_module.addImport(alias, dep.module(module))`. Set
`pass_target: false` or `pass_optimize: false` for package build scripts that do
not declare those dependency options.

Link artifacts from `build.zig.zon` package dependencies:

```cue
app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	pkg_artifacts: [{
		package: "zglfw"
		artifact: "glfw"
		pass_optimize: false
	}]
}
```

This maps to `root_module.linkLibrary(dep.artifact(artifact))` after resolving
the package dependency with the same target and optimize forwarding controls.

---

### `build_options`

Top-level `options` declare typed `b.option` values. A module lists the option
names it wants exposed through a generated options import:

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
	build_options_import: "build-options"
}
```

Supported option types are `bool`, `string`, and `u32`.

---

### `pre` and `post`

`pre` commands run before the module artifact compiles. Use them for simple
code-generation or stamping steps that do not yet need output-file tracking.
`post` commands run after the artifact install step and are suited to copy,
sign, or package commands.

```cue
pre: [{ argv: ["zig", "run", "tools/gen.zig"] }]
post: [{ argv: ["cp", "zig-out/bin/app", "dist/app"] }]
```

---

### `native`

Native metadata covers C sources and platform link inputs:

```cue
native: {
	c_sources: ["src/native.c"]
	include_dirs: ["include"]
	system_libs: ["sqlite3"]
	pkg_config_libs: ["libinput"]
	frameworks: ["CoreFoundation"]
	link_libc: true
}
```

It maps onto `std.Build.Module` APIs such as `addCSourceFile`,
`addIncludePath`, `linkSystemLibrary`, `linkFramework`, `link_libc`, and
`link_libcpp`. `pkg_config_libs` uses `linkSystemLibrary` with forced
pkg-config resolution.

---

### `kind`

Required. One of `"exe"`, `"static"`, `"shared"`, `"module"`. Decides which
`std.Build` call `build.zig` makes and where the artifact lands.

```cue
package build

hello: #Module & {
	kind: "exe"
	root: "src/main.zig"
}
```

```
$ ./gen_build_spec.sh && zig build && ls zig-out/bin
Generated build_spec.zig
hello
```

Change one word:

```cue
hello: #Module & {
	kind: "static"
	root: "src/main.zig"
}
```

```
$ ./gen_build_spec.sh && zig build && ls zig-out/lib
Generated build_spec.zig
libhello.a
```

An unrecognised value is rejected before anything is generated:

```
$ cue export -e build
app.kind: 3 errors in empty disjunction:
app.kind: conflicting values "exe" and "dylib":
    ./project.cue:4:6
    ./project.cue:5:8
    ./schema.cue:3:11
    ./schema.cue:7:12
app.kind: conflicting values "shared" and "dylib":
    ./project.cue:4:6
    ./project.cue:5:8
    ./schema.cue:3:30
    ./schema.cue:7:12
app.kind: conflicting values "static" and "dylib":
    ./project.cue:4:6
    ./project.cue:5:8
    ./schema.cue:3:19
    ./schema.cue:7:12
```

One error per branch of the disjunction. The last file:line in each block is
the schema rule; the first is your declaration.

Omitting `kind` gives a different error, because the field has no default:

```
$ cue export -e build
build.modules.app.kind: incomplete value "exe" | "static" | "shared":
    ./export.cue:10:14
```

---

### `root`

Required. The root source file, as a path relative to the directory holding
`build.zig`.

```cue
protocol: #Module & {
	kind:    "static"
	root:    "src/protocol.zig"
	profile: "release"
}
```

CUE checks the type and nothing else. It never touches the filesystem, so a
path that does not exist passes validation. From `examples/02-lib-and-app`
with `root` pointed at a file that is not there:

```
$ cue export -e build
{
    "modules": {
        "mathlib": {
            "kind": "static",
            "root": "src/nope.zig",
            "deps": [],
            "optimize": "Debug"
        },
        "calc": {
            "kind": "exe",
            "root": "src/calc.zig",
            "deps": [
                "mathlib"
            ],
            "optimize": "ReleaseFast"
        }
    }
}
```

The spec tests catch it, which is why they exist:

```
$ zig build test
test
+- run test 4/5 passed, 1 failed
error: 'spec_test.test.every module root exists on disk' failed: missing root for module 'mathlib': src/nope.zig
```

Without them you get the compiler's version:

```
$ zig build
install
+- install mathlib
   +- compile lib mathlib Debug native 1 errors
error: failed to check cache: 'src/nope.zig' file_hash FileNotFound
```

A non-string is rejected outright:

```
$ cue export -e build
app.root: conflicting values 42 and string (mismatched types int and string):
    ./project.cue:4:6
    ./project.cue:6:8
    ./schema.cue:8:12
```

---

### `deps`

Optional, `[...string]`, default `[]`. Each entry is the name of another
module. For each one, `build.zig` calls `linkLibrary`.

```cue
mathlib: #Module & {
	kind: "static"
	root: "src/mathlib.zig"
}

calc: #Module & {
	kind:    "exe"
	root:    "src/calc.zig"
	deps:    ["mathlib"]
	profile: "release"
}
```

**A dependency is a link edge.** It gives you no Zig import. This is the
single thing most likely to surprise you.

```
$ zig build
src/calc.zig:3:25: error: no module named 'mathlib' available within module 'root'
const mathlib = @import("mathlib");
                        ^~~~~~~~~
```

Symbols cross the boundary the way they would from a C library:

```zig
// src/mathlib.zig
pub export fn mathlib_add(a: i32, b: i32) i32 {
    return a + b;
}

// src/calc.zig
extern fn mathlib_add(a: i32, b: i32) i32;
```

```
$ ./zig-out/bin/calc
calc built as ReleaseFast
  add(2, 3)         = 5
  mul(6, 7)         = 42
  clamp(15, 0, 10)  = 10
```

Order does not matter. `build.zig` creates every compile step before it
resolves any dependency, so a module may depend on one declared later in the
file.

Multiple dependencies and repeated dependents are both fine:

```cue
gateway: #Module & {
	kind:    "exe"
	root:    "src/gateway.zig"
	deps:    ["protocol", "codec"]
	profile: "release"
}
```

CUE checks the type but cannot check the names. `deps` is `[...string]`, and
CUE has no view of which modules exist. A wrong name gets through validation
and kills `build.zig` during configuration:

```
$ zig build
thread 868007 panic: attempt to use null value
/path/to/azazel/build.zig:43:44: 0x1002a0033 in build (build)
            step.linkLibrary(built.get(dep).?);
                                           ^
```

Read that panic as "a name in `deps` is not in `export.cue`'s `_modules`".
The spec tests cannot help here, because they run after configuration.

A wrong type is caught:

```
$ cue export -e build
app.deps: 2 errors in empty disjunction:
app.deps: conflicting values "mathlib" and [...string] (mismatched types string and list):
    ./project.cue:4:6
    ./project.cue:7:8
    ./schema.cue:9:8
app.deps: conflicting values "mathlib" and [] (mismatched types string and list):
    ./project.cue:4:6
    ./project.cue:7:8
    ./schema.cue:9:23
```

Cycles are not rejected by CUE either. `build_spec_test.zig` runs Kahn's
algorithm over the declared edges and fails if any module is left unresolved.

---

### `link`

Optional. One of `"abi"` or `"import"`. Default `"abi"`. It controls how a
module is consumed by the things that depend on it.

`"abi"` is the original model. The module is compiled to its own artifact and
linked over the C ABI. Symbols cross the edge as `pub export fn` on the
dependency and `extern fn` on the dependent. This is what you need for a shared
library with a stable ABI, and for linking C or C++. A `shared` module is always
`abi`; the schema forces it.

`"import"` merges the module into each dependent as a plain Zig module. The
dependent reaches it with `@import("<name>")`, the same way it would reach any
Zig package. There is no separate artifact and no link step: the dependency
compiles as part of whatever imports it.

```cue
core: #Module & {
	kind: "static"
	root: "src/core.zig"
	link: "import"
}

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	deps: ["core"]
}
```

```zig
// src/core.zig
pub fn add(a: i32, b: i32) i32 {
	return a + b;
}

// src/main.zig
const core = @import("core");
pub fn main() void {
	_ = core.add(2, 3);
}
```

The source contract differs between the two. An `abi` dependency exports C-ABI
symbols and the dependent declares them `extern`. An `import` dependency is
ordinary Zig (`pub fn`) and the dependent `@import`s it. Switching a module's
`link` means writing its edge the matching way.

Prefer `import` for pure Zig-to-Zig dependencies. It rebuilds much faster
because the whole graph is one compilation, so Zig caches and re-links once
instead of validating and linking one artifact per module. The gap grows with
the module count. On a 150-module graph, a one-module change rebuilds in a few
hundred milliseconds under `import` against several seconds under `abi`. Keep
`abi` where the boundary is real: shared libraries, and edges that cross into C
or C++.

At large scale the two flat models trade places. All `abi` re-validates and
re-links a graph of hundreds of artifacts on every build. All `import` keeps the
graph small but turns each incremental into a recompile of the whole program, so
its cost grows with the codebase. The answer is to combine them: group modules
into **clusters**, each an `import` graph behind one `abi` module, and link the
clusters to each other over the ABI. A change then recompiles one cluster and
relinks, which stays flat as the project grows. On a 2000-module graph, clustered
builds rebuild a one-module change in about two seconds and build clean in about
ten, against roughly two minutes and ninety seconds for the all-`abi` model. See
[`examples/06-clusters`](../examples/06-clusters/).

---

### `profile`

Optional, `#Profile`, default `"debug"`. It is a name, and `#Profiles` maps
it to a Zig `OptimizeMode`.

| `profile` | `optimize` in the spec | Zig |
|-----------|------------------------|-----|
| `"debug"` | `"Debug"` | `.Debug` |
| `"release"` | `"ReleaseFast"` | `.ReleaseFast` |

Per module, so one build can mix them:

```cue
gateway: #Module & {
	kind:    "exe"
	root:    "src/gateway.zig"
	deps:    ["protocol", "codec"]
	profile: "release"
}

worker: #Module & {
	kind: "exe"
	root: "src/worker.zig"
	deps: ["protocol"]
}
```

```
$ ./zig-out/bin/gateway
gateway (ReleaseFast)
  magic       = 0xA2A2
  frame bytes = 12
  verify      = true
  tampered    = false

$ ./zig-out/bin/worker
worker (Debug)
  magic    = 0xA2A2
  job      = resize:1920x1080
  checksum = 574250979
```

An unknown profile is rejected:

```
$ cue export -e build
app.profile: 2 errors in empty disjunction:
app.profile: 3 errors in empty disjunction:
app.profile: conflicting values "debug" and "turbo":
    ./project.cue:4:6
    ./project.cue:7:11
    ./schema.cue:4:11
    ./schema.cue:10:12
app.profile: conflicting values "release" and "turbo":
    ./project.cue:4:6
    ./project.cue:7:11
    ./schema.cue:4:21
    ./schema.cue:10:12
```

`profile` is the only field with an indirection. Nothing else in the schema
goes through a lookup table, which is what makes profiles the natural place
to extend.

---

### `#Kind`

```cue
#Kind: "exe" | "static" | "shared"
```

| Value | `build.zig` call | Artifact | Installed to |
|-------|------------------|----------|--------------|
| `"exe"` | `addExecutable` | `name` | `zig-out/bin/` |
| `"static"` | `addLibrary(.linkage = .static)` | `libname.a` | `zig-out/lib/` |
| `"shared"` | `addLibrary(.linkage = .dynamic)` | `libname.dylib` / `libname.so` | `zig-out/lib/` |

All three in one build:

```
$ ls zig-out/bin zig-out/lib
zig-out/bin:
gateway
worker

zig-out/lib:
libcodec.dylib
libprotocol.a
```

The names follow the target. Cross-compiling the same `project.cue`:

```
$ zig build -Dtarget=x86_64-linux --prefix zig-out-x
$ ls zig-out-x/bin zig-out-x/lib
zig-out-x/bin:
gateway
worker

zig-out-x/lib:
libcodec.so
libprotocol.a

$ file zig-out-x/bin/gateway
zig-out-x/bin/gateway: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), dynamically linked, with debug_info, not stripped
```

Adding a fourth kind means editing `#Kind` in `schema.cue` and adding a case
to the `switch` in `build.zig`. Everything else follows.

---

### `#Profile` and `#Profiles`

```cue
#Profile: "debug" | "release"

#Profiles: {
	debug: {
		optimize: "Debug"
	}
	release: {
		optimize: "ReleaseFast"
	}
}

profiles: #Profiles
```

`#Profile` is the set of names you may write. `#Profiles` maps each name to
a `std.builtin.OptimizeMode` spelling. `export.cue` performs the lookup:

```cue
optimize: profiles[v.profile].optimize
```

The generator already understands all four Zig modes: `Debug`,
`ReleaseFast`, `ReleaseSafe`, `ReleaseSmall`. Adding a profile takes two
edits to `schema.cue`.

Add the name:

```cue
#Profile: "debug" | "release" | "small"
```

Add the mapping:

```cue
#Profiles: {
	debug: {
		optimize: "Debug"
	}
	release: {
		optimize: "ReleaseFast"
	}
	small: {
		optimize: "ReleaseSmall"
	}
}
```

Use it:

```cue
hello: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	profile: "small"
}
```

```
$ ./gen_build_spec.sh && zig build && ./zig-out/bin/hello
Generated build_spec.zig
hello from azazel (optimize=ReleaseSmall)
```

`ReleaseSafe` works the same way:

```
$ ./gen_build_spec.sh && zig build && ./zig-out/bin/hello
Generated build_spec.zig
hello from azazel (optimize=ReleaseSafe)
```

A mode outside those four dies in the generator, at the lookup table:

```
$ ./gen_build_spec.sh
Traceback (most recent call last):
  File "<string>", line 10, in <module>
KeyError: 'SuperFast'
$ echo $?
1
```

That leaves a truncated `build_spec.zig` behind, since the header is written
before the module list. Fix `#Profiles` and rerun; the file is rewritten from
scratch each time.

---

### `export.cue`

`export.cue` is the second half of declaring a module, and the half people
forget.

```cue
package build

_modules: {
	"core": core
	"app":  app
}

build: modules: {
	for k, v in _modules {
		(k): {
			kind:     v.kind
			root:     v.root
			deps:     v.deps
			optimize: profiles[v.profile].optimize
		}
	}
}
```

`_modules` is the list of modules that get built. The comprehension below it
projects each one into the shape the generator reads, resolving `profile` to
`optimize` on the way.

`project.cue` describes modules. `export.cue` decides which of them exist as
far as the build is concerned. A module in one and not the other is dropped
with no warning:

```
$ cue vet
$ echo $?
0

$ ./gen_build_spec.sh
Generated build_spec.zig
```

```zig
pub const modules = [_]Module{
    .{
        .name = "app",
        .kind = .exe,
        .root = "src/main.zig",
        .deps = &.{},
        .optimize = .Debug,
    },
};
```

Order in `_modules` is the order in the generated array. It has no effect on
linking.

---

## From build_spec.zig to build.zig

`gen_build_spec.sh` writes a fixed header and then one struct literal per
module:

```zig
const std = @import("std");

pub const Kind = enum { exe, static, shared };

pub const Module = struct {
    name: []const u8,
    kind: Kind,
    root: []const u8,
    deps: []const []const u8,
    optimize: std.builtin.OptimizeMode,
};

pub const modules = [_]Module{
    .{
        .name = "core",
        .kind = .static,
        .root = "src/core.zig",
        .deps = &.{},
        .optimize = .Debug,
    },
    .{
        .name = "app",
        .kind = .exe,
        .root = "src/main.zig",
        .deps = &.{ "core" },
        .optimize = .ReleaseFast,
    },
};
```

The field-by-field correspondence:

| Spec field | Source | Used by `build.zig` as |
|------------|--------|----------------------|
| `.name` | the key in `_modules` | artifact name, hash-map key |
| `.kind` | `kind` | the `switch` that picks `addExecutable` or `addLibrary` |
| `.root` | `root` | `b.path(m.root)` as `root_source_file` |
| `.deps` | `deps` | names looked up in the hash map, then `linkLibrary` |
| `.optimize` | `profiles[profile].optimize` | `.optimize` on the created module |

`build.zig` imports it at comptime and makes two passes:

```zig
const spec = @import("build_spec.zig");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});

    var built = std.StringHashMap(*std.Build.Step.Compile).init(b.allocator);
    defer built.deinit();

    // Pass 1: one Compile step per module.
    for (spec.modules) |m| {
        const mod = b.createModule(.{
            .root_source_file = b.path(m.root),
            .target = target,
            .optimize = m.optimize,
        });

        const step = switch (m.kind) {
            .exe => b.addExecutable(.{ .name = m.name, .root_module = mod }),
            .static => b.addLibrary(.{ .name = m.name, .root_module = mod, .linkage = .static }),
            .shared => b.addLibrary(.{ .name = m.name, .root_module = mod, .linkage = .dynamic }),
        };

        built.put(m.name, step) catch unreachable;
    }

    // Pass 2: resolve deps by name and install.
    for (spec.modules) |m| {
        const step = built.get(m.name).?;
        for (m.deps) |dep| {
            step.linkLibrary(built.get(dep).?);
        }
        b.installArtifact(step);
    }
}
```

The example `build.zig` files differ in two small ways. They spell the link
call `step.root_module.linkLibrary(...)`, which works on 0.14 and 0.15 and
survives Zig 0.16 moving `linkLibrary` off `Compile`. And they give every
executable an rpath so an installed binary can find an installed shared
library:

```zig
if (m.kind == .exe) {
    step.root_module.addRPathSpecial(switch (target.result.os.tag) {
        .macos, .ios, .tvos, .watchos => "@loader_path/../lib",
        else => "$ORIGIN/../lib",
    });
}
```

Without it the only rpath Zig writes points into `.zig-cache`, relative to
the current directory, and `zig-out/bin/gateway` runs from the project
directory and nowhere else:

```
dyld[5991]: Library not loaded: @rpath/libcodec.dylib
  Reason: tried: '.zig-cache/o/59c0702a5054dc7de34617670bdb6c38/libcodec.dylib' (no such file)
```

The repo root's `build.zig` omits it because nothing there is an executable
that links a shared library. Add it if you write one.

Two passes, because pass 1 has to have created every step before pass 2 can
look any of them up. That is what makes declaration order irrelevant.

Three consequences worth knowing.

**Everything is installed.** Libraries as well as executables. Anything in
`_modules` ends up in `zig-out`.

**One target for the whole graph.** `standardTargetOptions` is read once and
applied to every module, so `zig build -Dtarget=x86_64-linux` cross-compiles
all of it at once. There is no per-module target field.

**`built.get(dep).?` is unchecked.** An unknown name is a panic during
configuration, before any step runs.

The repo's `build.zig` adds one thing beyond the above: a `test` step over
three suites, `build_spec_test.zig`, `src/core_test.zig` and
`src/danzig/tests.zig`. `build_spec_test.zig` asserts the invariants the
loop depends on: unique names, `.zig` roots, roots present on disk, every
`dep` resolvable, no self-dependency, no cycles.

---

## Examples

Four runnable projects under `examples/`. Each is self-contained. Copy one
somewhere else and it still builds.

| Directory | Demonstrates |
|-----------|--------------|
| [`01-hello`](../examples/01-hello/) | The minimum module. Both defaults. |
| [`02-lib-and-app`](../examples/02-lib-and-app/) | `deps`, `profile`, static linkage, the C-ABI boundary. |
| [`03-services`](../examples/03-services/) | All three kinds, a shared library, multiple deps, mixed profiles. |
| [`04-validation`](../examples/04-validation/) | Every rejection the schema performs, with real `cue` output. |
| [`05-import-mode`](../examples/05-import-mode/) | `link: "import"`, a dependency merged as a Zig module instead of linked. |
| [`06-clusters`](../examples/06-clusters/) | Clusters: `import` graphs behind `abi` boundaries, the shape for large projects. |

Each has its own README with exact commands and their output.

```sh
cd examples/03-services
./gen_build_spec.sh
zig build
./zig-out/bin/gateway
zig build test --summary all
```

To build and test all of them at once:

```sh
./setup.sh --examples
```

The older `examples/*.cue` files (`minimal.cue`, `microservice.cue`,
`multi_lib.cue`) are illustrative fragments. They are not runnable on their
own.

---

## Editor support

`ide/vscode` contains a dependency-free VS Code extension for authoring
`project.cue` files. It provides CUE syntax highlighting, inline `cue export -e
build` diagnostics, and two azazel graph warnings that CUE cannot express:

- a `deps` string that names no module in `project.cue`
- a module that is absent from `export.cue`'s `_modules` map

It also provides completion for `#Module` fields and enum values, hover help for
fields and enum values, go-to-definition from a dependency string to its module
declaration, and the `Azazel: Generate build_spec` command.

Open `ide/vscode` in VS Code and press F5 to try it from source. The shared
language feature logic is also exposed by the stdio LSP prototype in
`ide/server/server.js`; run `node ide/server/test-client.js` for a smoke test.

---

## Huge project corpus

Azazel's small examples are smoke tests, not the target ceiling. The large-repo
pressure suite is tracked in [HUGE_PROJECT_CORPUS.md](HUGE_PROJECT_CORPUS.md).
It records real build graph shapes from ten projects: ZLS, libxev, River,
Mach, MicroZig, libvaxis, Capy, zig-gamedev, TigerBeetle, and Ghostty, plus the
gaps those projects expose in Azazel and Zaza.

Use `tools/huge_corpus.py --plan --expect-count 10` to write a preflight
`corpus-plan.json` and prove the full batch is selected. Use
`tools/huge_corpus.py --roadmap --expect-count 10` to write
`corpus-roadmap.md` plus issue-ready markdown files under `corpus-issues/` from
the same manifest data. Use `tools/huge_corpus.py --prepare` to create the fork overlays,
`tools/huge_corpus.py --audit` to record the host Zig baseline,
`tools/huge_corpus.py --doctor` to check local toolchains and host prerequisites,
`tools/huge_corpus.py --build` to prove the upstream build with the declared
toolchain, `tools/huge_corpus.py --parity` to emit `parity-results.json`, and
`tools/huge_corpus.py --executable-parity` to run modeled Azazel target slices.
Build reports include first target slices, replacement gaps, required tools,
pkg-config probes, and a concrete next action. Parity reports compare the
observed baseline classification with each repo's manifest. Executable parity
reports regenerate Azazel's `build_spec.zig` inside `.azazel/parity-work/` and
run the generated Zig build for any target slice marked ready.

The first executable Azazel slices are `libxev`, `libvaxis`, and
`zig-gamedev`. `libxev` proves plain import-mode module compilation by pointing
`module:xev` at upstream `src/main.zig` and compiling a generated
`exe:xev_probe`. `libvaxis` adds package-backed module compilation:
`module:vaxis` imports local `zigimg` and `uucode` path dependencies through the
generated parity workspace's `build.zig.zon`. `zig-gamedev` compiles the shared
sample `samples/common/src/vectormath.zig` module through a generated
`exe:zig_gamedev_vectormath_probe` on Zig `0.15.2` and imports the pinned
`zmath`, `zopengl`, `zglfw`, `zmesh`, and `znoise` packages through the parity
workspace's `build.zig.zon`. The `zglfw`, `zmesh`, and `znoise` slices also
link their exported native artifacts, which proves package artifact linking
plus native/framework metadata traversal. These slices prove real Azazel graphs
can compile upstream source and package dependencies, but they do not claim full
replacement; library variants, pkg-config/manpage
generation, generated Unicode table options, benchmarks, examples, assets, and
full example selection remain tracked gaps.

As of the current 10-repo proof plan, `libxev`, `libvaxis`, `zig-gamedev`, and
`tigerbeetle` build successfully with their declared Zig lanes. The other corpus projects are
blocked by concrete non-Azazel issues: ZLS's supported dev-toolchain window,
River host system dependencies, Mach's custom Zig mirror, MicroZig dependency
fetching, Capy's transitive package-format drift, and Ghostty's macOS
app-bundle packaging path.

---

## Troubleshooting

### `unable to load 'build_spec.zig': FileNotFound`

```
$ zig build
build_spec.zig:1:1: error: unable to load 'build_spec.zig': FileNotFound
build.zig:2:22: note: file imported here
const spec = @import("build_spec.zig");
                     ^~~~~~~~~~~~~~~~
```

The spec has not been generated. It is gitignored, so a fresh clone never has
one.

```sh
./gen_build_spec.sh
```

### `cue: command not found`

```
$ ./gen_build_spec.sh
./gen_build_spec.sh: line 8: cue: command not found
$ echo $?
127
```

Install CUE, or run `./setup.sh --check-only` to see what is missing.
`gen_build_spec.sh` calls `cue` by name and does not honour a `CUE`
environment variable; `setup.sh` does, and puts it on `PATH` for the
generator.

### A module I added does not get built

Check `export.cue`. A module in `project.cue` that is absent from `_modules`
is dropped silently. `cue vet` returns 0 and `gen_build_spec.sh` prints its
usual success line.

### `thread N panic: attempt to use null value` in build.zig

```
$ zig build
thread 868007 panic: attempt to use null value
/path/to/azazel/build.zig:43:44: 0x1002a0033 in build (build)
            step.linkLibrary(built.get(dep).?);
                                           ^
```

A name in some module's `deps` is not a module. Compare the `deps` lists in
`project.cue` against the keys in `export.cue`'s `_modules`. Typos and
modules you forgot to export both land here.

### `error: no module named 'X' available within module 'root'`

```
$ zig build
src/calc.zig:3:25: error: no module named 'mathlib' available within module 'root'
const mathlib = @import("mathlib");
                        ^~~~~~~~~
```

`deps` links a library. It does not register a Zig module. Export the symbols
you need with `pub export fn` and declare them with `extern fn` on the other
side. See [`deps`](#deps).

Note that Zig analyses top-level declarations lazily, so an unused
`@import` of a non-existent module compiles fine. The error appears the first
time you use it.

### `failed to check cache: 'src/X.zig' file_hash FileNotFound`

The `root` path in `project.cue` is wrong. Paths are relative to the
directory containing `build.zig`. `zig build test` gives the better message:

```
error: 'spec_test.test.every module root exists on disk' failed: missing root for module 'mathlib': src/nope.zig
```

### `some instances are incomplete`

```
$ cue vet
some instances are incomplete; use the -c flag to show errors or -c=false to allow incomplete instances
```

A required field is unset somewhere. `cue vet` will not say which. Run
`cue export -e build` instead, which names it:

```
build.modules.app.kind: incomplete value "exe" | "static" | "shared":
    ./export.cue:10:14
```

### `field not allowed`

```
$ cue export -e build
app.flags: field not allowed:
    ./project.cue:8:2
```

`#Module` is closed. Only `kind`, `root`, `deps`, `profile`, `link`, and `post`
exist. If you need something else, add it to the schema and generator, or wire
it into `build.zig` directly.

### `conflicting values "X" and "Y"`

An enumerated field got a value outside its disjunction. One error line per
branch. The schema file:line at the end of each block tells you which
disjunction it was.

### `dyld: Library not loaded: @rpath/libX.dylib`

An executable that links a `kind: "shared"` module cannot find it at runtime.
Zig's only rpath points into `.zig-cache`, relative to the current directory.
Give the executable an rpath relative to itself:

```zig
if (m.kind == .exe) {
    step.root_module.addRPathSpecial(switch (target.result.os.tag) {
        .macos, .ios, .tvos, .watchos => "@loader_path/../lib",
        else => "$ORIGIN/../lib",
    });
}
```

`examples/03-services/build.zig` does this. The repo root's `build.zig` does
not, because it has no executable that links a shared library.

### Changes to project.cue seem to have no effect

`build_spec.zig` is generated on demand. Nothing watches for you. Run
`./gen_build_spec.sh` after every edit to `project.cue`, `export.cue` or
`schema.cue`.

### A Zig version outside the declared lanes

Azazel's generated spec declares supported lanes under `toolchain.zig.lanes`.
The default lanes are `0.14`, `0.15`, and `0.16`. `build.zig` checks the current
compiler against that list at compile time and stops with a toolchain error if
the lane is unsupported.

This is deliberate: Zig build APIs move quickly, and a clean lane error is more
useful than a later failure inside `std.Build`, a dependency build script, or a
generated source step.

---

## File reference

| File | Role | How often you edit it |
|------|------|-----------------------|
| `project.cue` | module declarations | every time the project changes |
| `export.cue` | which modules get built | whenever you add or remove one |
| `schema.cue` | types and defaults | rarely; new kinds or profiles |
| `gen_build_spec.sh` | `cue export` to Zig source | never |
| `build_spec.zig` | generated module array | never; gitignored |
| `build.zig` | walks the spec, builds the graph | never, in normal use |
| `setup.sh` | toolchain check, generate, build, test | never |
| `build_spec_test.zig` | invariants over the generated spec | when adding invariants |

---

## Links

- Repository: <https://github.com/godofecht/azazel>
- Examples: [`examples/`](../examples/)
- CUE: <https://cuelang.org/>
- Zig build system: <https://ziglang.org/learn/build-system/>
