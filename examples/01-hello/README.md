# 01-hello

The smallest possible azazel project: one executable, no dependencies.

## What it demonstrates

- The two required `#Module` fields, `kind` and `root`.
- The two defaults. `deps` is omitted and resolves to `[]`. `profile` is
  omitted and resolves to `"debug"`, which maps to `.Debug`.
- The full pipeline in one directory: `project.cue` in, a binary out.

## Layout

```
01-hello/
  schema.cue          type definitions (identical to the repo root's)
  project.cue         the module declaration
  export.cue          wires module names into the generated spec
  gen_build_spec.sh   CUE -> build_spec.zig (identical to the repo root's)
  build.zig           walks build_spec.zig and creates the compile graph
  src/main.zig
```

`build_spec.zig` is generated. It is gitignored.

## Run it

```sh
cd examples/01-hello
./gen_build_spec.sh
zig build
./zig-out/bin/hello
```

Output:

```
$ ./gen_build_spec.sh
Generated build_spec.zig

$ zig build

$ ./zig-out/bin/hello
hello from azazel (optimize=Debug)
```

## What CUE resolved

`cue export -e build` shows the config after defaults are filled in:

```
$ cue export -e build
{
    "modules": {
        "hello": {
            "kind": "exe",
            "root": "src/main.zig",
            "deps": [],
            "optimize": "Debug"
        }
    }
}
```

Note that `deps` and `optimize` appear even though `project.cue` never
mentions them. CUE supplies them from `schema.cue`.

## What was generated

```zig
pub const modules = [_]Module{
    .{
        .name = "hello",
        .kind = .exe,
        .root = "src/main.zig",
        .deps = &.{},
        .optimize = .Debug,
    },
};
```

## Try changing it

Set a release profile:

```cue
hello: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	profile: "release"
}
```

Then:

```sh
./gen_build_spec.sh && zig build && ./zig-out/bin/hello
```

The binary reports the mode it was compiled with:

```
hello from azazel (optimize=ReleaseFast)
```

## Verified with

Zig 0.14.1 and 0.15.2, CUE v0.16.0.
