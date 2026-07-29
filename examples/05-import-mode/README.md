# 05-import-mode

A dependency consumed as a Zig module rather than a linked artifact.

## What it demonstrates

- The `link` field. `mathlib` is `link: "import"`, so it does not become its own
  `libmathlib.a`. It merges into `app` as a Zig module.
- The source contract for an import edge. `mathlib` is ordinary Zig (`pub fn`),
  and `app` reaches it with `@import("mathlib")`. No `pub export fn`, no
  `extern fn`, no C ABI.
- The build shape that results: one compile step, one artifact.

Compare [`02-lib-and-app`](../02-lib-and-app/), which links the same two-module
shape over the C ABI (`link: "abi"`, the default).

## Layout

```
05-import-mode/
  schema.cue          type definitions (identical to the repo root's)
  project.cue         mathlib (link: "import") and app
  export.cue          wires module names into the generated spec
  gen_build_spec.sh   CUE -> build_spec.zig (identical to the repo root's)
  build.zig           walks the spec; import deps use addImport, abi deps link
  src/mathlib.zig     pub fn add / mul
  src/main.zig        @import("mathlib")
```

## Run it

```sh
./gen_build_spec.sh && zig build && ./zig-out/bin/app
```

```
add(2, 3) = 5
mul(4, 5) = 20
```

`zig-out` holds only `bin/app`. There is no `lib/libmathlib.a`, because
`mathlib` was compiled inside `app` rather than linked to it.

## Why import mode

An `import` edge is one compilation instead of one artifact per module, so Zig
caches and links once. Rebuilds get much faster, and the gap grows with the
module count. On a 150-module graph through this same pipeline:

| operation | `abi` (default) | `import` |
|-----------|-----------------|----------|
| clean build | 12.7s | 5.2s |
| no-op build | 4.5s | 0.3s |
| one-module change | 4.9s | 0.5s |

Reach for `import` on pure Zig-to-Zig dependencies. Keep `abi` where the
boundary is real: a shared library with a stable ABI, or an edge that crosses
into C or C++. A `shared` module is always `abi`.
