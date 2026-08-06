# Shared content-addressed cache

`cache_key.sh` and `cache_build.sh` turn Azazel's build-as-data into a portable,
shareable artifact cache — the transferable half of a remote build cache, without
the remote-execution machinery.

## The key is computed from the model, not discovered by compiling

`cache_key.sh` prints a content key for the build, computed **without invoking the
compiler**, from:

- the normalized build model (`cue export`),
- every `.zig` source under each module root (content-hashed),
- the pinned dependency identities in `build.zig.zon` (url + hash),
- the toolchain (the model's preferred lane and the resolved `zig version`).

Identical inputs produce an identical key on any machine. Over-invalidation is
sound: a superfluous miss just rebuilds; a stale hit cannot happen, because any
changed input changes the key.

## Skip the build on a hit

```sh
SHARED=/path/to/shared/store  sh cache_build.sh
```

It computes the key, and if `$SHARED/<key>.tar` exists it restores `zig-out` and
skips the build; otherwise it builds and stores the output under the key. Point
`$SHARED` at a directory a team and CI share (a network mount, or synced to an
object store) and the first machine to build a given input set shares the result
with everyone.

## Why Zig's own cache doesn't already do this

Zig's cache is local and content-addressed per artifact, so a warm rebuild on the
*same* machine is fast. But a fresh machine with an empty `~/.cache/zig` has to
rebuild from scratch. Azazel can compute the whole-build key from the committed
model *before* running the compiler, so a fresh machine addresses the shared
store and restores the finished artifact instead of building.

Measured (libvaxis slice, zigimg + uucode): a fresh machine cold-builds in ~9.3s;
a second fresh machine with an empty Zig cache but a shared store restores it in
~0.6s — **~15×**, no compilation.
