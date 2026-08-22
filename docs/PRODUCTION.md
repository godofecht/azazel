# Production support policy

Azazel's production-supported surface is the deterministic configuration pipeline:

```text
project.cue -> cue export -> build_spec.zig -> build.zig -> artifacts
```

The goal of this contract is to let projects keep a stable declarative build
model while Azazel absorbs `std.Build` API churn across supported Zig lanes.

## Supported core

The following are part of the supported core when exercised through the
canonical `azazel` CLI or the equivalent `gen_build_spec.sh` + `zig build`
pipeline:

- CUE schema validation and default resolution;
- executable, static, shared, and module targets;
- import and ABI dependency edges;
- artifact-name overrides;
- typed build options and fixed option values;
- Zig package module imports and package artifacts;
- local/native source metadata and platform libraries;
- generated Zig imports produced by declared host tools;
- install-directory staging;
- Zig toolchain lane rejection before build execution.

A field is not considered supported merely because it exists in `schema.cue`.
It must survive CUE export, code generation, and the Zig executor. CI validates
that the full module contract is exported and runs the canonical CLI on every
supported Zig lane.

## Supported toolchains

Release CI currently covers Zig 0.14.1, 0.15.2, and 0.16.0. Those are the
supported production lanes for this release line. Zig 0.17 support is useful for
corpus work but remains best-effort while 0.17 is a moving development target.

CUE is pinned in CI because its resolved export is part of the build-model
contract. Python 3 is required only for code generation and the CLI; generated
build execution itself is Zig.

## Compatibility policy

Azazel is pre-1.0. Schema changes that alter the meaning of an existing field,
generated `build_spec.zig` changes that require coordinated executor changes,
and removals of supported Zig lanes are treated as breaking changes and must be
called out in release notes.

Within a release line, a project model that validates should not silently change
meaning. Unsupported combinations should fail during validation or generation,
not degrade into a different build topology.

## Experimental surfaces

The following are intentionally outside the production contract:

- shared artifact caching in `cache_build.sh`;
- corpus/fork automation under `tools/huge_corpus.py`;
- Danzig, which is retained as an integration/dogfood workload;
- editor tooling under `ide/` unless separately versioned and released.

Experimental code may be valuable and heavily tested, but it must not be
required for a normal Azazel build. The shared cache is explicitly disabled by
default because its key does not yet prove a complete build-input closure.

## Release gate

A release intended for production adoption must satisfy all of the following:

1. `python3 azazel check` succeeds from a clean checkout.
2. `python3 azazel gen` is deterministic when forced to regenerate.
3. `python3 azazel build` succeeds on every supported Zig lane.
4. `zig build test --summary all` succeeds on every supported Zig lane.
5. The exported module object contains every field consumed by the generator.
6. Documentation does not describe experimental behavior as a correctness guarantee.
7. Real-project parity documentation distinguishes target-slice proof from full-project replacement.

## Adoption guidance

For a production project, pin the Azazel revision or release used by CI and keep
`project.cue`, `export.cue`, and the generated-executor version in lockstep.
Upgrade Azazel deliberately and run the project's complete build/test/package
matrix before changing the pin.

Do not use the experimental shared cache for release artifacts. Use Zig's normal
build/cache path until the cache input-closure work is complete.
