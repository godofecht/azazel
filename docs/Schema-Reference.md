# Schema Reference

`schema.cue` defines the type system. You should rarely need to modify it.

## Types

### `#Kind`

```cue
#Kind: "exe" | "static" | "shared" | "module"
```

| Value | Zig equivalent |
|-------|---------------|
| `"exe"` | `addExecutable` |
| `"static"` | `addStaticLibrary` |
| `"shared"` | `addSharedLibrary` |
| `"module"` | `createModule`, no artifact |

### `#Profile`

```cue
#Profile: "debug" | "release"
```

| Value | Zig `OptimizeMode` |
|-------|-------------------|
| `"debug"` | `.Debug` |
| `"release"` | `.ReleaseFast` |

### `#ZigLane`

```cue
#ZigLane: "0.14" | "0.15" | "0.16"
```

Azazel tracks Zig by minor-version lane because `std.Build` changes between
releases. Projects can narrow the default lane list with top-level
`toolchain.zig.lanes`.

### `#Module`

```cue
#Module: {
    kind:     #Kind
    root:     string
    deps:     [...string] | *[]
    profile:  #Profile | *"debug"
    link:     #Link | *"abi"
    pre:      [...#Command] | *[]
    post:     [...#Command] | *[]
    pkg_imports: [...#PackageImport] | *[]
    pkg_artifacts: [...#PackageArtifact] | *[]
    build_options: [...string] | *[]
    build_options_import: string | *"build-options"
    native:   #Native | *{}
}
```

All validation happens at `cue vet` / `cue export` time. Invalid values are rejected before any Zig code is generated.

## Profiles

```cue
profiles: {
    debug:   { optimize: "Debug" }
    release: { optimize: "ReleaseFast" }
}
```

To add a new profile (e.g. `small`), add it to `#Profile`, add its entry to `profiles`, and it becomes available in `project.cue`.

## Toolchain

```cue
toolchain: zig: {
    lanes: ["0.14", "0.15", "0.16"]
    preferred: "0.15"
}
```

The generator emits these lanes into `build_spec.zig`; `build.zig` rejects an
unsupported host Zig lane before doing dependency or compilation work.

## Build Options

```cue
#Option: {
    name: string
    type: "bool" | "string" | "u32"
    description: string | *""
    default?: bool | string | int
}
```

Top-level `options` declare project options. A module lists option names in
`build_options` to receive them through `build_options_import`.

## Package Imports

```cue
#Package: {
    url?: string
    hash?: string
    path?: string
    lazy: bool | *false
}

#PackageImport: {
    alias: string
    package: string
    module: string
    pass_target: bool | *true
    pass_optimize: bool | *true
}

#PackageArtifact: {
    package: string
    artifact: string
    pass_target: bool | *true
    pass_optimize: bool | *true
}
```

Top-level `packages` records package dependency intent for diagnostics and
corpus reporting. Zig still resolves actual package dependencies from
`build.zig.zon`.

`pkg_imports` attach modules from Zig package dependencies. By default Azazel
passes the target and module optimize mode into `b.dependency`. Set
`pass_optimize: false` or `pass_target: false` for packages whose build scripts
do not declare those dependency options.

`pkg_artifacts` link compiled artifacts exported by Zig package dependencies.
They use the same dependency option forwarding controls, then map to
`root_module.linkLibrary(dep.artifact(artifact))`.

## Native Metadata

```cue
#Native: {
    c_sources: [...string] | *[]
    include_dirs: [...string] | *[]
    system_include_dirs: [...string] | *[]
    library_paths: [...string] | *[]
    object_files: [...string] | *[]
    system_libs: [...string] | *[]
    pkg_config_libs: [...string] | *[]
    frameworks: [...string] | *[]
    link_libc: bool | *false
    link_libcpp: bool | *false
}
```

These fields map to `std.Build.Module` native-link APIs. `pkg_config_libs`
forces pkg-config resolution for the listed system libraries.

## What the Schema Rejects

| Input | Error |
|-------|-------|
| `kind: "dylib"` | Not in `#Kind` disjunction |
| `profile: "turbo"` | Not in `#Profile` disjunction |
| `toolchain: zig: lanes: ["0.17"]` | Not in `#ZigLane` disjunction |
| `root: 42` | Type mismatch: expected `string` |
| Missing `kind` | Incomplete value |
| Missing `root` | Incomplete value |
