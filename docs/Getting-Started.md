# Getting Started

## Prerequisites

- Zig 0.14.1, 0.15.2, or 0.16.0 for the supported release lanes
- CUE v0.16.0
- Python 3 for validation/code generation

## Setup

```sh
git clone https://github.com/godofecht/azazel.git
cd azazel
./setup.sh --check-only
```

## Validate

Run the same contract check used by CI:

```sh
python3 azazel check
```

This validates the CUE model, verifies that the full module schema survives the
export layer, checks module roots and dependency references, and rejects cycles.

## Build

```sh
python3 azazel gen
python3 azazel build
```

`azazel gen` delegates to the canonical `gen_build_spec.sh`; the CLI does not
maintain a second generator implementation.

The equivalent low-level path is:

```sh
./gen_build_spec.sh
zig build
```

Normal Zig build arguments can be forwarded through the CLI:

```sh
python3 azazel build -Dfoo=true
```

## Test

```sh
zig build test --summary all
```

## Run the repository fixture

```sh
./zig-out/bin/app
```

## Inspect resolved configuration

```sh
python3 azazel info
```

For production guarantees and experimental boundaries, read
[`PRODUCTION.md`](PRODUCTION.md). The shared artifact cache is experimental and
disabled by default; do not use it for release artifacts.
