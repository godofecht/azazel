# Project File

`project.cue` is the only file you edit. It declares your modules — what to build, from what source, with what dependencies.

## Structure

Every module is a `#Module` with these fields:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `kind` | `"exe"` `"static"` `"shared"` | yes | — | Output type |
| `root` | `string` | yes | — | Root source file path |
| `deps` | `[...string]` | no | `[]` | Names of modules this depends on |
| `profile` | `"debug"` `"release"` | no | `"debug"` | Optimization profile |

## Minimal Example

```cue
package build

app: #Module & {
    kind: "exe"
    root: "src/main.zig"
}
```

One module. Four lines. Debug mode by default.

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
