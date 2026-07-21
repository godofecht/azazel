# 03-services

Four modules: one static library, one shared library, two executables.

## What it demonstrates

- All three `#Kind` values in one graph.
- `kind: "shared"` producing a real `.dylib`/`.so`, and an executable
  loading it at runtime.
- A module with more than one dependency (`gateway` links `protocol` and
  `codec`).
- A library depended on by three modules.
- Mixed profiles inside one build. `worker` stays on the default `debug`,
  everything else is `release`, and each binary prints the mode it was
  compiled with.

## The graph

```
protocol (static, release)
   ^   ^   ^
   |   |   +----------------- worker  (exe, debug)
   |   +--------------------- gateway (exe, release)
   +-- codec (shared, release) <-- gateway
```

`gateway` links both libraries. `worker` links only `protocol`.

## Layout

```
03-services/
  schema.cue
  project.cue
  export.cue
  gen_build_spec.sh
  build.zig
  spec_test.zig          asserts kinds, profiles and graph shape
  src/protocol.zig       MAGIC + checksum, exported C-ABI
  src/codec.zig          frame encode/verify, links protocol
  src/codec_test.zig
  src/gateway.zig
  src/worker.zig
```

## Run it

```sh
cd examples/03-services
./gen_build_spec.sh
zig build
./zig-out/bin/gateway
./zig-out/bin/worker
zig build test --summary all
```

Output:

```
$ ./gen_build_spec.sh
Generated build_spec.zig

$ zig build

$ ls zig-out/bin zig-out/lib
zig-out/bin:
gateway
worker

zig-out/lib:
libcodec.dylib
libprotocol.a

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

$ zig build test --summary all
Build Summary: 5/5 steps succeeded; 14/14 tests passed
test success
+- run test 7 passed 468ms MaxRSS:1M
|  +- compile test Debug native success 701ms MaxRSS:237M
+- run test 7 passed 263ms MaxRSS:1M
   +- compile test Debug native success 700ms MaxRSS:238M
```

On Linux `libcodec.dylib` is `libcodec.so`. Nothing in `project.cue` changes.

`gateway` says `ReleaseFast`, `worker` says `Debug`. That difference comes
entirely from the one `profile` line in `project.cue`.

## What CUE resolved

```
$ cue export -e build
{
    "modules": {
        "protocol": {
            "kind": "static",
            "root": "src/protocol.zig",
            "deps": [],
            "optimize": "ReleaseFast"
        },
        "codec": {
            "kind": "shared",
            "root": "src/codec.zig",
            "deps": [
                "protocol"
            ],
            "optimize": "ReleaseFast"
        },
        "gateway": {
            "kind": "exe",
            "root": "src/gateway.zig",
            "deps": [
                "protocol",
                "codec"
            ],
            "optimize": "ReleaseFast"
        },
        "worker": {
            "kind": "exe",
            "root": "src/worker.zig",
            "deps": [
                "protocol"
            ],
            "optimize": "Debug"
        }
    }
}
```

## What was generated

```zig
pub const modules = [_]Module{
    .{
        .name = "protocol",
        .kind = .static,
        .root = "src/protocol.zig",
        .deps = &.{},
        .optimize = .ReleaseFast,
    },
    .{
        .name = "codec",
        .kind = .shared,
        .root = "src/codec.zig",
        .deps = &.{ "protocol" },
        .optimize = .ReleaseFast,
    },
    .{
        .name = "gateway",
        .kind = .exe,
        .root = "src/gateway.zig",
        .deps = &.{ "protocol", "codec" },
        .optimize = .ReleaseFast,
    },
    .{
        .name = "worker",
        .kind = .exe,
        .root = "src/worker.zig",
        .deps = &.{ "protocol" },
        .optimize = .Debug,
    },
};
```

## Notes on the source

`deps` is a link edge, so nothing here uses `@import` across module
boundaries. `protocol.zig` exposes `protocol_magic` and `protocol_checksum`
as `pub export fn`. `codec.zig` and the two executables declare them as
`extern fn` and let the linker match them up.

`src/codec_test.zig` imports `protocol.zig` directly, because a test binary
is one compilation and has no libprotocol.a to link against. The
`comptime { _ = protocol; }` block forces protocol's exported symbols into
the test binary so `codec.zig`'s `extern` declarations resolve.

## Note on the shared library

`build.zig` gives every executable an rpath of `@loader_path/../lib`
(`$ORIGIN/../lib` outside Apple platforms):

```zig
if (m.kind == .exe) {
    step.root_module.addRPathSpecial(switch (target.result.os.tag) {
        .macos, .ios, .tvos, .watchos => "@loader_path/../lib",
        else => "$ORIGIN/../lib",
    });
}
```

Without it, the only rpath on the binary points into `.zig-cache`, relative to
the current directory. `zig-out/bin/gateway` would then run from the example
directory and nowhere else:

```
dyld[5991]: Library not loaded: @rpath/libcodec.dylib
  Reason: tried: '.zig-cache/o/59c0702a5054dc7de34617670bdb6c38/libcodec.dylib' (no such file)
```

With it, `zig-out/bin` and `zig-out/lib` move together and the binary works
from any working directory. The repo root's `build.zig` does not do this,
because nothing there is an executable that links a shared library.

## Verified with

Zig 0.14.1 and 0.15.2 on macOS arm64, CUE v0.16.0.
