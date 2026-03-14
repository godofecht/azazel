# Examples

All examples live in the `examples/` directory. To use one, copy it to `project.cue` and update `export.cue`'s `_modules` map.

## Minimal — Single Executable

**`examples/minimal.cue`**

```cue
package build

app: #Module & {
    kind: "exe"
    root: "src/main.zig"
}
```

**`export.cue` modules:**
```cue
_modules: {
    "app": app
}
```

Produces one binary at `zig-out/bin/app`.

## Multi-Library — Shared + Static + Exe

**`examples/multi_lib.cue`**

```cue
package build

math: #Module & {
    kind: "shared"
    root: "src/math.zig"
    profile: "release"
}

utils: #Module & {
    kind: "static"
    root: "src/utils.zig"
}

app: #Module & {
    kind:    "exe"
    root:    "src/main.zig"
    deps:    ["math", "utils"]
    profile: "release"
}
```

**`export.cue` modules:**
```cue
_modules: {
    "math":  math
    "utils": utils
    "app":   app
}
```

Demonstrates mixed library types. `math` is shared (`.dylib`/`.so`), `utils` is static (`.a`), `app` links both.

## Microservice — Protocol + Two Services

**`examples/microservice.cue`**

```cue
package build

protocol: #Module & {
    kind:    "static"
    root:    "src/protocol.zig"
    profile: "release"
}

gateway: #Module & {
    kind:    "exe"
    root:    "src/gateway.zig"
    deps:    ["protocol"]
    profile: "release"
}

worker: #Module & {
    kind:    "exe"
    root:    "src/worker.zig"
    deps:    ["protocol"]
    profile: "release"
}
```

**`export.cue` modules:**
```cue
_modules: {
    "protocol": protocol
    "gateway":  gateway
    "worker":   worker
}
```

Produces two binaries (`gateway`, `worker`) both linking a shared protocol library. All optimized for release.
