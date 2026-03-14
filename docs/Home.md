# Azazel

A deterministic build system using **CUE** for constraint validation and **Zig** for execution.

No JSON runtime. No flags. No ceremony.

## How It Works

```
project.cue  →  CUE validates + resolves  →  build_spec.zig  →  zig build
 (human)           (schema.cue)                (generated)        (engine)
```

1. You edit `project.cue` — the only file you touch
2. Run `./gen_build_spec.sh` — CUE validates your config against the schema and emits a Zig source file
3. Run `zig build` — Zig reads the generated spec at compile time, zero parsing overhead

## Documentation

- [Getting Started](Getting-Started.md)
- [Project File](Project-File.md)
- [Schema Reference](Schema-Reference.md)
- [Examples](Examples.md)
- [Code Generation](Code-Generation.md)
- [Architecture](Architecture.md)
