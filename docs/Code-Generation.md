# Code Generation

Azazel generates Zig source code, not JSON. The build system never parses anything at runtime.

## Pipeline

```
schema.cue + project.cue + export.cue
        ↓
    cue export -e build       (JSON to stdout, internal only)
        ↓
    gen_build_spec.sh         (transforms JSON → Zig source)
        ↓
    build_spec.zig            (compile-time constant array)
        ↓
    build.zig @import         (pure Zig, zero overhead)
```

## Generated Output

For a project with `core` (static) and `app` (exe, release), `build_spec.zig` looks like:

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

## Why Not JSON?

- No runtime parsing cost
- No `std.json` dependency in the build
- Type-safe at compile time — Zig catches mismatches before execution
- The generated file is human-readable and auditable

## Regenerating

Run the script whenever you change `project.cue`:

```sh
./gen_build_spec.sh
```

`build_spec.zig` is gitignored — it's a build artifact.
