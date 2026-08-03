# Project File

`project.cue` is the only file you edit. It declares your modules — what to build, from what source, with what dependencies.

## Structure

Every module is a `#Module` with these fields:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `kind` | `"exe"` `"static"` `"shared"` `"module"` | yes | — | Output type |
| `root` | `string` | yes | — | Root source file path |
| `deps` | `[...string]` | no | `[]` | Names of modules this depends on |
| `profile` | `"debug"` `"release"` | no | `"debug"` | Optimization profile |
| `link` | `"abi"` `"import"` | no | `"abi"` | Whether dependents link or import this module |
| `pre` | command list | no | `[]` | Commands to run before compiling this module |
| `post` | command list | no | `[]` | Commands to run after installing this module |
| `install_dirs` | install directory list | no | `[]` | Stages asset/content directories |
| `pkg_imports` | package import list | no | `[]` | Imports from `build.zig.zon` dependencies |
| `pkg_artifacts` | package artifact list | no | `[]` | Links artifacts from `build.zig.zon` dependencies |
| `build_options` | `[...string]` | no | `[]` | Names of typed options to expose to the module |
| `native` | native metadata | no | `{}` | C sources, include dirs, system libs, frameworks |

You can also declare the supported Zig lanes for the project:

```cue
toolchain: zig: {
    lanes: ["0.14", "0.15", "0.16"]
    preferred: "0.15"
}
```

Leave it out for the default three maintained lanes. Narrow it when a project
depends on one Zig minor release's `std.Build` API.

## Minimal Example

```cue
package build

app: #Module & {
    kind: "exe"
    root: "src/main.zig"
}
```

One executable. Three lines. Debug mode by default.

Use `kind: "module"` for a named Zig module that other targets import but that
should not produce a static library or executable.

## Package Imports

Top-level `packages` can mirror the dependency intent from `build.zig.zon` for
diagnostics and corpus reporting:

```cue
packages: known_folders: {
    url: "https://example.invalid/known-folders.tar.gz"
    hash: "..."
    lazy: false
}
```

Use `pkg_imports` when the module imports a dependency from `build.zig.zon`:

```cue
app: #Module & {
    kind: "exe"
    root: "src/main.zig"
    pkg_imports: [{
        alias: "known-folders"
        package: "known_folders"
        module: "known-folders"
    }]
}
```

This maps to:

```zig
const dep = b.dependency("known_folders", .{ .target = target, .optimize = optimize });
module.addImport("known-folders", dep.module("known-folders"));
```

Set `pass_target: false` or `pass_optimize: false` on a `pkg_imports` entry
when the package build script does not declare those dependency options.
Set `backend: "glfw_wgpu"` when a package dependency exposes a `backend`
enum option and must be selected at dependency time. Azazel passes the same
backend value to package imports and package artifacts.

Use `pkg_artifacts` when the module must link a compiled artifact exported by a
package dependency:

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

This maps to:

```zig
const dep = b.dependency("zglfw", .{ .target = target });
module.linkLibrary(dep.artifact("glfw"));
```

For packages such as `zgui` that export both a module and a native artifact,
put the same `backend` value on both entries:

```cue
pkg_imports: [{
    alias: "zgui"
    package: "zgui"
    module: "root"
    backend: "glfw_wgpu"
}]
pkg_artifacts: [{
    package: "zgui"
    artifact: "imgui"
    backend: "glfw_wgpu"
}]
```

Use `pkg_library_paths` when a package helper normally adds a prebuilt library
directory to the consuming artifact. Pair it with `native.system_libs` when the
artifact must also link a system library name:

```cue
pkg_artifacts: [{
    package: "zgpu"
    artifact: "zdawn"
}]
pkg_library_paths: [{
    package: "dawn_aarch64_macos"
    os: "macos"
    arch: "aarch64"
}]
native: {
    system_libs: ["dawn"]
}
```

Use `install_dirs` to stage runtime assets:

```cue
app: #Module & {
    kind: "exe"
    root: "src/main.zig"
    install_dirs: [{
        source_dir: "assets"
        install_dir: "bin"
        install_subdir: "assets"
    }]
}
```

This maps to `b.addInstallDirectory` and is attached to the default install
step.

## Build Options

Declare typed options once, then opt modules into an options import:

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

This exposes `@import("build-options").enable_tracy` through Zig's generated
options module.

## Native Metadata

Use `native` for C and platform linkage:

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

## Generated Commands

Use `pre` for code generators that must run before compilation and `post` for
copy/sign/package commands that run after the artifact is installed:

```cue
pre: [{ argv: ["zig", "run", "tools/gen.zig"] }]
post: [{ argv: ["cp", "zig-out/bin/app", "dist/app"] }]
```

## With Dependencies

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

`app` links against `core`. Released with `ReleaseFast` optimization.

## Wiring Modules to Export

When you add or remove modules in `project.cue`, update the `_modules` map in `export.cue` to match:

```cue
_modules: {
    "core": core
    "app":  app
}
```

This map is the single source of truth for what gets generated into `build_spec.zig`.
