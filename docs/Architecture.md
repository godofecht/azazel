# Architecture

## Design Principles

1. **Deterministic** — CUE ensures schema + default resolution. Same input always produces same output.
2. **Minimal surface** — Users see 4 fields: `kind`, `root`, `deps`, `profile`. Nothing else leaks through.
3. **No JSON runtime** — CUE exports Zig source. Build reads it at compile time.
4. **Separation of concerns** — CUE is purely declarative. Zig is purely execution.

## File Roles

| File | Role | Edit frequency |
|------|------|---------------|
| `project.cue` | Declare modules | Every time you add/change a target |
| `export.cue` | Wire modules to output | When adding/removing module names |
| `schema.cue` | Type definitions + defaults | Rarely — only to add new kinds/profiles |
| `gen_build_spec.sh` | CUE → Zig codegen | Never |
| `build_spec.zig` | Generated module array | Never (gitignored) |
| `build.zig` | Zig build interpreter | Never |

## What Is NOT Exposed

These are intentionally hidden from the user:

- Compiler flags
- Include paths
- Macro definitions
- Platform triples
- Internal Zig build knobs
- Linker options

All of these are resolved by schema defaults or the Zig build engine.

## Build Engine (`build.zig`)

The Zig side is a ~40 line loop:

1. **Pass 1** — iterate `spec.modules`, create the appropriate `Compile` step for each (`addExecutable`, `addStaticLibrary`, or `addSharedLibrary`), store in a hash map by name
2. **Pass 2** — iterate again, resolve `deps` by name lookup, call `linkLibrary`, install executables

Two passes are needed because dependencies may reference modules defined later in the array.

## Extending

### Adding a new profile

1. Add the value to `#Profile` in `schema.cue`
2. Add its optimization mapping to `profiles`
3. Use it in `project.cue`

### Adding a new module kind

1. Add the value to `#Kind` in `schema.cue`
2. Handle it in `build.zig`'s switch statement

### Future directions

- Multi-platform matrix expansion
- Feature toggles
- Test targets
- Package integration
- Remote cache compatibility
