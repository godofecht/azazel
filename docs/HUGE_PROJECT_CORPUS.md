# Huge Zig Project Corpus

This corpus tracks large real-world Zig projects used to pressure-test Azazel
and Zaza beyond toy `zig run` examples.

Environment for the first pass:

- Date: 2026-07-31
- Host Zig: 0.14.0
- Clone root: `/tmp/azazel-huge`

Forks live under `godofecht/*`; integration branches use
`azazel-zaza-integration`. Use `tools/huge_corpus.py` to prepare, audit, or
produce build/parity-readiness reports for the corpus:

```sh
tools/huge_corpus.py --prepare --push
tools/huge_corpus.py --audit
tools/huge_corpus.py --doctor
tools/huge_corpus.py --build
tools/huge_corpus.py --parity
tools/huge_corpus.py --executable-parity
tools/huge_corpus.py --audit --repo zls --repo microzig
```

## Baseline Audit

| Project | Shape | Baseline result on host Zig | Pressure points |
| --- | --- | --- | --- |
| `zigtools/zls` | Language server with generated version data, tests, coverage, release signing, package deps | `zig build --help` fails: ZON import needs newer Zig result typing | Zig version constraints, generated run artifacts, package deps, build options, release-only post commands |
| `mitchellh/libxev` | Cross-platform event-loop library with static/dynamic libs, examples, benches, manpage generation | `zig build --help` fails: build script expects `b.graph.io` | Library variants, conditional examples, manpage generators, platform system libs |
| `riverwm/river` | Wayland compositor with pkg-config/system deps and generated translation modules | `zig build --help` fails: ZON import needs newer Zig result typing | External dependency diagnostics, pkg-config system libraries, C sources, generated translate-C modules |
| `hexops/mach` | Game engine with modules, examples, editor project, generated Vulkan bindings, native backends | Fails on required custom Mach Zig version and newer FS API | Custom Zig toolchain constraints, assets, backend options, generated sources, helper build APIs |
| `ZigEmbeddedGroup/microzig` | Embedded workspace with many nested `build.zig` and `.zon` packages | Fails on newer Zig language syntax: `@Struct` and inline asm clobber syntax | Workspace/package graph, embedded targets, tools, board ports, nested build packages |
| `rockorager/libvaxis` | TUI library with many examples and test/install steps | `zig build --help` fails on Zig 0.14 format/build API incompatibility | Example matrix, installable demos, tests, host Zig compatibility diagnostics |
| `capy-ui/capy` | Native UI toolkit with custom build helper | Fails fast: requires Zig 0.14.1 exactly | Minimum/exact Zig version constraints, platform UI backends, custom helper build layer |
| `zig-gamedev/zig-gamedev` | Large game-dev monorepo with assets and package deps | Clone required heavy filtering; build help fails in deps (`zphysics`, `ztracy`) on Zig 0.14 | Large asset graphs, dependency API drift, package-level diagnostics, optional example selection |

## Integration Branches

Prepared and pushed on the forks:

| Fork | Branch |
| --- | --- |
| `godofecht/zls` | `azazel-zaza-integration` |
| `godofecht/libxev` | `azazel-zaza-integration` |
| `godofecht/river` | `azazel-zaza-integration` |
| `godofecht/mach` | `azazel-zaza-integration` |
| `godofecht/microzig` | `azazel-zaza-integration` |
| `godofecht/libvaxis` | `azazel-zaza-integration` |
| `godofecht/capy` | `azazel-zaza-integration` |
| `godofecht/zig-gamedev` | `azazel-zaza-integration` |

Each branch has a `.azazel/` scaffold with repo metadata, a starting
`project.cue`, integration notes, and `.azazel/parity.json`. The parity manifest
records the preferred Zig lane, baseline command, expected baseline failure
classification, first Azazel target slice, and required system dependencies.
The scaffold intentionally leaves upstream source untouched; full parity work
proceeds feature by feature against the baseline audit.

## Parity Reports

Run:

```sh
tools/huge_corpus.py --parity
tools/huge_corpus.py --parity --repo zls --repo libxev
```

The runner writes `parity-results.json` in the clone root. Each entry records:

- the exact baseline command and return code
- the observed baseline classification
- whether the observed classification matches the repo manifest
- Azazel's declared parity command and current status
- first target slices to implement before claiming full-project parity

The current manifests mark Azazel status as `scaffold-only`. That is deliberate:
the reports are allowed to prove that the corpus is blocked by toolchain/API
gaps, but they must not claim replacement parity until Azazel can actually
translate and run the declared target slice.

## Executable Azazel Parity

Run:

```sh
tools/huge_corpus.py --executable-parity
tools/huge_corpus.py --executable-parity --repo libxev
```

`--executable-parity` writes `executable-parity-results.json` in the clone root.
For repos with a modeled target slice, the runner creates an isolated
`.azazel/parity-work/` workspace, regenerates `build_spec.zig`, resolves the
repo's declared Zig toolchain, and runs the Azazel-generated build command.
Repos without a modeled slice report `not-modeled` instead of fake success.

The first executable slice is `libxev`:

- `module:xev` points at upstream `src/main.zig`
- `exe:xev_probe` imports the module through Azazel's `link: "import"` graph
- Zig `0.16.0` compiles the generated Azazel build successfully

This proves an Azazel target slice can execute against upstream source. It does
not claim full libxev build replacement yet; library variants, generated
pkg-config/manpage outputs, benchmarks, examples, and artifact checks remain
tracked replacement gaps.

## Build Proof Reports

Run:

```sh
tools/huge_corpus.py --doctor
tools/huge_corpus.py --build
tools/huge_corpus.py --build --repo libxev --repo zig-gamedev
```

`--doctor` checks the local machine prerequisites declared by each manifest:
toolchain path, required host tools, and pkg-config libraries. It writes
`doctor-results.json` in the clone root and gives a next action before running a
full build.

`--build` resolves the manifest's declared Zig toolchain, runs the repo's actual
build command, and writes `build-results.json` in the clone root. The report is
intentionally separate from parity: a repo can build with its upstream
`build.zig` while Azazel remains `scaffold-only`. Each build result also records
the first target slice, known replacement gaps, required tools, pkg-config
probes, and the next action for moving toward replacement parity.

Fresh proof run on 2026-07-31 from `/tmp/azazel-huge-proof`:

| Project | Zig used | Build result | Meaning |
| --- | --- | --- | --- |
| `zls` | `0.17-dev` | `zig-toolchain` | ZLS rejects current master `0.17.0-dev.1509+bb296ab9b`; the older accepted dev build is no longer available from the Zig build archive. |
| `libxev` | `0.16.0` | `ok` | Upstream build succeeds. |
| `river` | `0.16.0` | `system-dependency` | Zig graph gets past API drift, then host `pkg-config` cannot locate `wayland-scanner`. |
| `mach` | `mach-2026.4.10` | `missing-toolchain` | Mach requires custom Zig `2026.4.10-mach`; the mirror currently redirects but returns `unable to fetch: UpstreamError` for the Apple Silicon archive. |
| `microzig` | `0.16.0` | `dependency-fetch` | Fetching the `lwip` zip dependency fails while creating Zig's temporary zip file. |
| `libvaxis` | `0.16.0` | `ok` | Upstream build succeeds. |
| `capy` | `0.14.1` | `dependency-format` | Transitive `zig-objc` dependency still uses string `.name`, rejected by Zig package parsing. |
| `zig-gamedev` | `0.15.2` | `ok` | Upstream build succeeds after repairing the integration branch to include upstream files plus `.azazel`. |

Current successful upstream builds: `libxev`, `libvaxis`, and `zig-gamedev`.
Current Azazel benefit is reproducible toolchain/build diagnostics plus fork
metadata. Full build replacement is not claimed yet. Zaza is not inserted into
these pure-Zig upstream build graphs unless a repo has a C/C++ target slice that
we explicitly model.

Current executable Azazel parity slices:

| Project | Slice | Result | Boundary |
| --- | --- | --- | --- |
| `libxev` | `module:xev` plus `exe:xev_probe` | `ok` on Zig `0.16.0` | Proves import-mode module compilation through Azazel; full install graph is still future work. |

## Doctor Output

`tools/huge_corpus.py --doctor` answers "can this host run the declared proof
command?" without cloning or compiling. Useful statuses:

| Field | Meaning |
| --- | --- |
| `toolchain.found` | The declared Zig binary can be resolved from the local toolchain root or an override env var. |
| `required_tools` | Host commands such as `pkg-config` or `wayland-scanner`. |
| `pkg_config_libs` | Libraries probed through `pkg-config --exists`. |
| `replacement_gaps` | Build-graph features Azazel/Zaza must model before claiming replacement value. |
| `next_action` | Concrete next step for the repo's current state. |

## Current Audit Results

`tools/huge_corpus.py --audit` on host Zig 0.14.0 reports:

| Project | Result |
| --- | --- |
| `zls` | fails before build graph execution: `@import` of ZON needs a known result type |
| `libxev` | fails before build graph execution: build script expects `b.graph.io` |
| `river` | fails before build graph execution: `@import` of ZON needs a known result type |
| `mach` | fails on newer filesystem API and explicit custom Mach Zig requirement |
| `microzig` | fails on newer Zig language syntax (`@Struct`, inline asm clobber syntax) |
| `libvaxis` | fails on host Zig format/build API drift |
| `capy` | fails fast: exact Zig 0.14.1 required |
| `zig-gamedev` | dependency build scripts fail on Zig API drift (`lto`, `std.fmt.printInt`) |

## Azazel Gaps Exposed

- Toolchain constraints: lane support now exists for `0.14`, `0.15`, and `0.16`; exact/custom toolchains still need richer metadata.
- Package dependencies: package module imports now exist; dependency declarations, hashes, paths, lazy dependencies, and failures still need richer modeling.
- Named modules without artifacts: `kind: "module"` now represents `b.addModule` and pure module imports.
- Build options: typed booleans, strings, and `u32` defaults now exist; enums/lists still need modeling.
- Generated sources: pre-build command nodes now exist; `addRunArtifact` output-file tracking still needs modeling.
- Native integration: C sources, include paths, link system libraries, pkg-config libraries, library paths, object files, frameworks, libc, and libc++ now exist.
- Multi-step outputs: support install/run/test/doc/sign/package steps without hard-coding one global install flow.
- Workspaces: support nested build packages and subprojects, especially MicroZig-style trees.
- Diagnostics: distinguish "unsupported host Zig", "dependency fetch failed", "system dependency missing", and "translation unsupported".

## Zaza Gaps Exposed

- Post-build commands need to compose with generated artifacts and installed artifacts across CMake and Zig branches.
- System-command enablement should produce precise errors naming the target and command that was skipped.
- C/C++ integration needs parity with Zig build metadata: include paths, link libraries, frameworks, and per-config commands.
- Large repo support now has per-repo parity manifests and the first executable Azazel parity slice for `libxev`; the next step is to expand slice coverage one repo at a time.

## Next Targets

1. Add enum/list build options.
2. Add package dependency declarations/hashes and dependency-fetch diagnostics.
3. Add generated-file/run-artifact output tracking.
4. Expand executable Azazel parity from the `libxev` module probe to library artifacts, tests, examples, and additional repos.
