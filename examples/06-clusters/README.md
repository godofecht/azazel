# 06-clusters

The shape to reach for on a large project: a handful of clusters, each an
internal `import` graph, linked to each other over the ABI.

## What it demonstrates

- Combining both `link` modes to get low build overhead and cheap incremental
  rebuilds at the same time.
- A **cluster**: a `link: "abi"` static module that `@import`s several
  `link: "import"` members. The members compile into the one cluster artifact.
- An **ABI boundary between clusters**: `app` links `geometry` and `stats` over
  the C ABI, so a change inside one cluster recompiles only that cluster and
  relinks `app`. The other cluster stays cached.

```
circle, square  --import-->  geometry (static, abi) --+
                                                       +--> app (exe)
mean, spread    --import-->  stats    (static, abi) --+
```

## Run it

```sh
./gen_build_spec.sh && zig build && ./zig-out/bin/app
```

```
geometry_total(1, 2) = 7.1416
stats_variance     = 4.0000
```

`zig-out/lib` holds `libgeometry.a` and `libstats.a`, one per cluster. The six
member modules have no artifacts of their own; they compiled into their cluster.
Edit `src/circle.zig` and rebuild: only `geometry` recompiles, `stats` is reused.

## Why cluster

Two flat models each fail at scale in opposite ways.

- All `abi` (one artifact per module) makes every build re-validate and re-link
  a huge graph. On 1000 modules a no-op build takes tens of seconds.
- All `import` (one compilation) keeps no-op builds cheap but makes every
  incremental recompile the whole program, so the incremental cost grows with
  the codebase.

Clustering takes the good half of each. A change costs one cluster recompile
plus a relink, which stays flat as you add more clusters. Measured on a
2000-module graph through this pipeline (clusters of 50):

| model | clean | no-op build | one-module change |
|-------|-------|-------------|-------------------|
| all `abi` | ~90s | ~90s | ~120s |
| all `import` | 31s | 2.0s | 12.2s |
| **clustered** | **9.3s** | **1.7s** | **1.9s** |

For reference, Bazel on the same graph rebuilt a one-module change in ~1.7s (its
incremental is flat by design) but took ~156s for a clean build. Clustered
azazel matches the incremental and builds clean an order of magnitude faster,
because each cluster is a single compilation instead of one compiler process per
module.

Tune the cluster size to the project. Bigger clusters mean fewer artifacts and a
lighter relink; smaller clusters mean a cheaper single-cluster recompile.
Somewhere around a few dozen to a hundred modules per cluster works well.
