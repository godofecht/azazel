# Getting Started

## Prerequisites

- [Zig](https://ziglang.org/download/) 0.14.0+
- [CUE](https://cuelang.org/docs/introduction/installation/) v0.16.0+
- Python 3 (for codegen script)

## Setup

```sh
git clone https://github.com/godofecht/azazel.git
cd azazel
```

## Build

```sh
./gen_build_spec.sh   # CUE → build_spec.zig
zig build             # compile everything
```

## Run

```sh
./zig-out/bin/app
```

## Validate Without Building

Check your `project.cue` against the schema without generating anything:

```sh
cue vet
```

## Inspect Resolved Config

See the fully normalized build data CUE produces:

```sh
cue export -e build
```
