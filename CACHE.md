# Experimental shared content-addressed cache

`cache_key.sh` and `cache_build.sh` are an experimental artifact-cache prototype.
They are **not part of Azazel's production-supported build contract yet**.

The core production path is:

```text
project.cue -> CUE validation -> build_spec.zig -> zig build
```

The cache is disabled by default. To experiment with it after reviewing the
limitations below:

```sh
AZAZEL_EXPERIMENTAL_CACHE=1 sh cache_build.sh
```

## What the current key covers

`cache_key.sh` currently derives a key from:

- the normalized CUE build model,
- reachable local `.zig` files found by walking literal `@import("*.zig")` edges
  from module roots,
- URL/hash identities present in `build.zig.zon`,
- the preferred Zig lane and resolved `zig version`,
- host OS and architecture.

This is enough to demonstrate portable whole-build caching for controlled
fixtures and some pure-Zig graphs. It is not yet a proof of a complete build
input closure.

## Known soundness gaps

A production remote cache must guarantee that every input capable of changing an
artifact changes the key. The current prototype does not yet model every such
input. Important examples include local C/C++ sources and headers, local path
dependency contents, system library/framework versions, arbitrary environment
variables read by build-time tools, undeclared files read by `pre`/`post`
commands, and all target/build-option combinations accepted by arbitrary Zig
package build scripts.

Because a cache hit restores `zig-out` and skips the build, an incomplete key can
produce a stale hit. For that reason `cache_build.sh` requires the explicit
`AZAZEL_EXPERIMENTAL_CACHE=1` opt-in.

Do not use this cache for release, security-sensitive, reproducible-build, or
production CI artifacts until the input-closure work is complete.

## Backends

The prototype supports two stores.

GitHub Releases can be used as a shared store:

```sh
AZAZEL_EXPERIMENTAL_CACHE=1 \
AZAZEL_CACHE_REPO=owner/azazel-cache \
sh cache_build.sh
```

The release tag defaults to `cache` and can be changed with
`AZAZEL_CACHE_RELEASE`.

A local or shared directory can also be used:

```sh
AZAZEL_EXPERIMENTAL_CACHE=1 \
SHARED=/path/to/shared/store \
sh cache_build.sh
```

## Promotion criteria

The cache can move into the production-supported surface only when Azazel has a
declared-input model that covers every local source/header/object, generated
input and output, path dependency, target, build option, relevant toolchain and
system dependency; CI has negative tests proving each input mutation invalidates
the key; and cache-hit artifacts are checked against clean-build artifacts over
the real-project parity corpus.

Until then, the cache remains useful research infrastructure rather than a
correctness guarantee.
