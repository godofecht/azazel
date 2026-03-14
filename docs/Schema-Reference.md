# Schema Reference

`schema.cue` defines the type system. You should rarely need to modify it.

## Types

### `#Kind`

```cue
#Kind: "exe" | "static" | "shared"
```

| Value | Zig equivalent |
|-------|---------------|
| `"exe"` | `addExecutable` |
| `"static"` | `addStaticLibrary` |
| `"shared"` | `addSharedLibrary` |

### `#Profile`

```cue
#Profile: "debug" | "release"
```

| Value | Zig `OptimizeMode` |
|-------|-------------------|
| `"debug"` | `.Debug` |
| `"release"` | `.ReleaseFast` |

### `#Module`

```cue
#Module: {
    kind:     #Kind
    root:     string
    deps:     [...string] | *[]
    profile:  #Profile | *"debug"
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

## What the Schema Rejects

| Input | Error |
|-------|-------|
| `kind: "dylib"` | Not in `#Kind` disjunction |
| `profile: "turbo"` | Not in `#Profile` disjunction |
| `root: 42` | Type mismatch: expected `string` |
| Missing `kind` | Incomplete value |
| Missing `root` | Incomplete value |
