# Shared content-addressed cache

`cache_build.sh` restores `zig-out` from a store when it holds an entry for the
build's key, and builds and stores one when it does not. A restored entry skips
compilation, so the key has to name every input that can change an artifact.
`tools/cache_closure.py` computes that key from the build's declared inputs. It
refuses to produce a key for a build whose inputs it cannot name.

```sh
sh cache_build.sh [zig build arguments...]
sh cache_key.sh [--explain] [zig build arguments...]
python3 azazel cache-key [--explain] [zig build arguments...]
```

`cache_key.sh` prints the key. With `--explain` it prints the digest of each
part and of each file that went into it. Exit status 3 means the build is not
cacheable, and the reasons follow on stderr. `AZAZEL_PROJECT` names the project
directory when it is not the directory that holds the scripts.

## What the key covers

The key is the digest of eleven parts. Each part has a mutation test that
changes one input and requires the part, and so the key, to change.

| Part | Inputs |
| --- | --- |
| `model` | The resolved CUE model: modules, native fields, package declarations with their typed `args`, options, profiles and optimize modes, generated steps, system dependencies, subprojects |
| `engine` | `build.zig`, `compat.zig`, `build.zig.zon`, `schema.cue`, `project.cue`, `export.cue`, `gen_build_spec.sh`, the CUE version, and the closure code itself |
| `toolchain` | The version that `zig version` reports and the content hash of the Zig binary |
| `target` | `-Dtarget`, `-Dcpu` and `-Ddynamic-linker`. With no `-Dtarget`, the native target, cpu model and features from `zig targets` |
| `options` | The effective value of every declared option, with defaults applied, the `-Dslice` and `-Dsubproject` selections, and the named steps |
| `sources` | Each module root, every `.zig` or data file reached through `@import`, and every file reached through `@embedFile` |
| `headers` | Each C or C++ source, every quoted `#include` it reaches, and every file under an `include_dirs` or `system_include_dirs` entry |
| `objects` | Each `object_files` entry and every file under a `library_paths` entry |
| `installs` | Every file under an `install_dirs` source directory |
| `generated` | A generator tool's source and imports, each `input_file`, `stdin`, and for a script generator the interpreter binary and the script |
| `packages` | The contents of every `path` package, and the url and hash of every fetched one |
| `system` | The `tool` system dependencies the project declares |

Paths are hashed relative to the project directory, so the key does not change
when the project moves.

Passing an option at its default value gives the key of leaving it out. The
order of repeated `-Dslice` flags does not matter. `--summary` and `--color`
have no effect on the key.

## What is refused

A build is refused, with one reason per cause, when it has any of these.

| Cause | Why |
| --- | --- |
| `pre` or `post` commands | They run arbitrary programs with inputs the key cannot see |
| A `command` generator that is not an interpreter running a declared script | The program is a binary whose behavior the closure cannot read |
| A generator script or tool that reads the environment, the clock, randomness, the network, or runs other programs | Its output is not a function of declared inputs. Python and shell scripts and Zig tools are scanned for these |
| `system_libs`, `pkg_config_libs`, `frameworks` | The key cannot see the contents of a host library |
| A `system_include_dirs` or `library_paths` entry with an absolute path | It names a directory outside the project |
| A `system_deps` entry of any kind except `tool` | A library, framework, header or directory on the host is an input the key cannot hash |
| `link_libc` or `link_libcpp` without `-Dtarget=<arch>-<os>-<abi>` naming a non-Apple ABI | A native libc is a host input. An explicit ABI uses the libc that Zig bundles |
| `ZIG_LIB_DIR`, `ZIG_LIBC`, `ZIG_BUILD_RUNNER`, `SDKROOT`, `DEVELOPER_DIR`, `MACOSX_DEPLOYMENT_TARGET`, `CPATH`, `C_INCLUDE_PATH`, `CPLUS_INCLUDE_PATH`, `LIBRARY_PATH`, `CC`, `CXX`, `CFLAGS`, `CXXFLAGS`, `LDFLAGS` set | They redirect the compiler, libc or SDK |
| A build argument outside `-Dtarget`, `-Dcpu`, `-Ddynamic-linker`, `-Dslice`, `-Dsubproject`, declared options, `--summary`, `--color` and `-j` | The key does not model it |
| A declared file that is missing or unreadable, a package with neither a path nor a url and hash, a Zig outside the declared lanes | The closure is incomplete |

A refused build reads nothing from the store and writes nothing to it.

## Entries

An entry is a tar of `zig-out` named `<key>.tar`. It carries a marker file with
the key it was stored under. A restore checks the marker, removes it, and
rebuilds when it does not match. A restored `zig-out` therefore holds the files
a clean build holds and nothing else.

## Evidence

`tools/test_cache_closure.py` holds the mutation tests, the refusal tests, and
end-to-end tests of `cache_build.sh` against a project with a C source, a header
and a static library. The end-to-end tests check that a miss stores, a hit
restores files equal to a clean build, a native source or header change misses,
a target change misses, a refused build touches nothing, and an entry stored
under another key is rejected.

`tools/cache_parity.py` compares a cache hit with a clean build on the corpus
slices of libvaxis and libxev. For each slice it:

1. builds twice from scratch and records the digest of every file in `zig-out`,
2. runs `cache_build.sh` against an empty store, which must miss,
3. removes `zig-out` and the Zig cache and runs it again, which must hit and
   restore files equal to the clean build and byte for byte equal to the miss,
4. appends an exported variable to the slice's probe, then to a source file in
   the upstream `src` tree, and requires the key to change, the run to miss, and
   the stored result to equal a clean build of the changed tree.

```sh
tools/huge_corpus.py --root DIR --executable-parity --repo libvaxis --repo libxev
tools/cache_parity.py --root DIR
AZAZEL_CACHE_PARITY_ROOT=DIR python3 -m unittest tools.test_cache_closure.RealSlices
```

The slices need Zig 0.16.0. On macOS two clean builds of one source differ in
`LC_UUID`, the ad-hoc code signature that covers it, and the debug-map entries,
which hold the object file's mtime and the Zig cache hash of the build. The
comparison blanks those fields in Mach-O files and compares everything else.
Hit against miss is compared byte for byte.

## Limits

- Artifacts built in Debug mode can embed the build directory in debug
  information. The key does not change when the project moves, so a hit
  restored in another directory runs the same code with different debug paths.
- A script generator can read a file it does not declare. The scan finds
  environment, clock, randomness, network and process use. It does not find an
  undeclared path opened by name. Declare every file a generator reads as an
  `input_file`.
- An interpreter is hashed as one binary. Its standard library and installed
  packages are not.
- The parity run covers macOS arm64 with Zig 0.16.0. The test suite in CI
  exercises the key and the scripts on Linux, and does not run the real-slice
  comparison.

## Backends

GitHub Releases can be used as a shared store:

```sh
AZAZEL_CACHE_REPO=owner/azazel-cache sh cache_build.sh
```

The release tag defaults to `cache` and can be changed with
`AZAZEL_CACHE_RELEASE`.

A local or shared directory can also be used:

```sh
SHARED=/path/to/shared/store sh cache_build.sh
```

Anyone who can write to a store can put an entry under any key. Use a store with
the access control of the artifacts you ship from it.
