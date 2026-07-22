# 02-lib-and-app

A static library and an executable that links it.

## What it demonstrates

- `deps`, and what a dependency edge actually means.
- `profile`, set per module. `mathlib` uses the default (`debug`), `calc`
  overrides it to `release`.
- `kind: "static"` producing `zig-out/lib/libmathlib.a`.
- A `zig build test` step that checks the generated spec before it checks
  the code.

## The one thing to understand about `deps`

`deps: ["mathlib"]` makes `build.zig` call `linkLibrary`. That is a linker
edge. It does **not** create a Zig module import.

```
$ zig build
src/calc.zig:3:25: error: no module named 'mathlib' available within module 'root'
const mathlib = @import("mathlib");
                        ^~~~~~~~~
```

Symbols cross the boundary as C-ABI symbols instead:

```zig
// src/mathlib.zig
pub export fn mathlib_add(a: i32, b: i32) i32 {
    return a + b;
}

// src/calc.zig
extern fn mathlib_add(a: i32, b: i32) i32;
```

This is the same contract you would get linking against a C library.

## Layout

```
02-lib-and-app/
  schema.cue
  project.cue
  export.cue
  gen_build_spec.sh
  build.zig             module graph + a test step
  spec_test.zig         asserts invariants about the generated spec
  src/mathlib.zig
  src/mathlib_test.zig
  src/calc.zig
```

## Run it

```sh
cd examples/02-lib-and-app
./gen_build_spec.sh
zig build
./zig-out/bin/calc
zig build test --summary all
```

Output:

```
$ ./gen_build_spec.sh
Generated build_spec.zig

$ zig build

$ ./zig-out/bin/calc
calc built as ReleaseFast
  add(2, 3)         = 5
  mul(6, 7)         = 42
  clamp(15, 0, 10)  = 10

$ zig build test --summary all
Build Summary: 5/5 steps succeeded; 8/8 tests passed
test success
+- run test 5 passed 502ms MaxRSS:1M
|  +- compile test Debug native success 741ms MaxRSS:237M
+- run test 3 passed 264ms MaxRSS:2M
   +- compile test Debug native success 737ms MaxRSS:234M
```

Artifacts:

```
$ ls zig-out/bin zig-out/lib
zig-out/bin:
calc

zig-out/lib:
libmathlib.a
```

## What was generated

```zig
pub const modules = [_]Module{
    .{
        .name = "mathlib",
        .kind = .static,
        .root = "src/mathlib.zig",
        .deps = &.{},
        .optimize = .Debug,
    },
    .{
        .name = "calc",
        .kind = .exe,
        .root = "src/calc.zig",
        .deps = &.{ "mathlib" },
        .optimize = .ReleaseFast,
    },
};
```

`mathlib` comes first because `export.cue` lists it first, and the generator
preserves that order. Order does not affect linking. `build.zig` creates every
compile step before it resolves any dependency, so a module may depend on one
declared later.

## Try breaking it

### A root file that does not exist

```sh
sed -i '' 's|src/mathlib.zig|src/nope.zig|' project.cue
./gen_build_spec.sh
```

`cue export` is happy. `root` is just a `string`, and CUE never touches the
filesystem. `zig build test` names the offending module:

```
$ zig build test
test
+- run test 4/5 passed, 1 failed
error: 'spec_test.test.every module root exists on disk' failed: missing root for module 'mathlib': src/nope.zig
```

`zig build` gets there too, less directly:

```
$ zig build
install
+- install mathlib
   +- compile lib mathlib Debug native 1 errors
error: failed to check cache: 'src/nope.zig' file_hash FileNotFound
```

### A dependency on a module that does not exist

```cue
deps: ["mathlibb"]
```

CUE accepts this as well. `deps` is `[...string]`, so any string is valid.
Here the spec test cannot save you, because `build.zig` walks the same array
during configuration and dies first:

```
$ zig build
thread 812200 panic: attempt to use null value
.../build.zig:48:56: 0x10444002b in build (build)
            step.root_module.linkLibrary(built.get(dep).?);
                                                       ^
```

`zig build test` panics identically. Configuration runs before any step does.
Read the panic as "a name in `deps` does not appear in `export.cue`'s
`_modules`".

## Verified with

Zig 0.14.1 and 0.15.2, CUE v0.16.0.
