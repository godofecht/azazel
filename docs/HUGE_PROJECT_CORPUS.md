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
tools/huge_corpus.py --plan --expect-count 10
tools/huge_corpus.py --roadmap --expect-count 10
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
| `tigerbeetle/tigerbeetle` | Distributed financial database with large test/release machinery | Host Zig `0.14.0` fails exact Zig `0.14.1` requirement | Large test matrix, release/package artifact graph, generated tooling, target-specific optimization/link settings |
| `ghostty-org/ghostty` | Terminal app with resources, platform integration, and packaging | Host Zig `0.14.0` fails on newer ZON/filesystem build APIs | Native dependency preflight, resource/app-bundle staging, package/sign steps, generated config/resources |

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
| `godofecht/tigerbeetle` | `azazel-zaza-integration` |
| `godofecht/ghostty` | `azazel-zaza-integration` |

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

## 10-Repo Batch Plan

Run:

```sh
tools/huge_corpus.py --plan --expect-count 10
```

The runner writes `corpus-plan.json` in the clone root before any clone or
build is needed. The plan records:

- the exact 10 repo names, upstreams, forks, and integration branch
- the declared Zig lane and resolved local toolchain path
- doctor readiness and missing host prerequisites
- expected baseline/build classifications
- first Azazel target slices and replacement gaps
- executable parity readiness

Use `--expect-count 10` with `--prepare`, `--doctor`, `--build`, `--parity`,
and `--executable-parity` as well. It fails fast if a narrowed repo selection
would accidentally run against fewer than the full batch.

All ten repos now have real baseline classifications. Reports reserve
`matches_expected: null` for future entries that are intentionally marked
`unverified` before their real baseline command has been run.

## Roadmap and Issue Output

Run:

```sh
tools/huge_corpus.py --roadmap --expect-count 10
```

The runner writes `corpus-roadmap.md` and one issue-ready markdown file per repo
under `corpus-issues/` in the clone root. These files are generated from the
same manifests and doctor preflight data as `corpus-plan.json`; they do not
claim build replacement, executable parity, or missing prerequisites that are
not present in the corpus metadata.

Each issue file records:

- upstream and fork names
- declared Zig lanes and expected classifications
- doctor readiness and missing prerequisites
- first target slices
- replacement gaps
- concrete next action
- acceptance criteria for moving that repo toward Azazel/Zaza replacement value

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

The first executable slices are:

- `module:xev` points at upstream `src/main.zig`
- `exe:xev_probe` imports the module through Azazel's `link: "import"` graph
- Zig `0.16.0` compiles the generated Azazel build successfully
- `module:vaxis` points at upstream `src/main.zig`
- `exe:vaxis_probe` imports the module through Azazel's `link: "import"` graph
- `package:zigimg` and `package:uucode` are wired through local `build.zig.zon`
  path dependencies in the parity workspace
- `module:zig_gamedev_vectormath` points at upstream
  `samples/common/src/vectormath.zig`
- `exe:zig_gamedev_vectormath_probe` imports the module through Azazel's
  `link: "import"` graph
- `package:zmath` is wired through a local `build.zig.zon` path dependency in
  the parity workspace
- `package:zopengl` is wired through the parity workspace with
  `pass_optimize: false`, matching its package build option surface
- `package:zglfw` is wired through the parity workspace with
  `pass_optimize: false`
- `artifact:zglfw:glfw` links the package's exported native GLFW artifact
- `package:zmesh` and `package:znoise` are wired through local `build.zig.zon`
  path dependencies in the parity workspace
- `artifact:zmesh:zmesh` and `artifact:znoise:FastNoiseLite` link additional
  exported native package artifacts
- `package:zgui` is wired through a local path dependency with
  `backend: "glfw_wgpu"`
- `artifact:zgui:imgui` links the backend-selected ImGui artifact
- `package:zgpu` and `artifact:zgpu:zdawn` cover the WGPU sample package and
  native Dawn wrapper surface
- `package-library-path:dawn_aarch64_macos` adds the real Dawn prebuilt package
  library search path for macOS arm64 parity
- `asset:sdl2_demo_content` stages the real
  `samples/sdl2_demo/sdl2_demo_content` directory into an explicit install
  prefix and verifies `zero.png` exists

This proves an Azazel target slice can execute against upstream source. It does
not claim full project build replacement yet; library variants, generated
pkg-config/manpage outputs, generated Unicode tables, benchmarks, examples, and
artifact checks and full example selection remain tracked replacement gaps.

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
| `tigerbeetle` | `0.14.1` | `ok` | Upstream build succeeds on its exact Zig lane. |
| `ghostty` | `0.16.0` | `platform-package` | Core/resource graph progresses, then the macOS app bundle path fails at `xcodebuild`/copy-bundle packaging. |

Current successful upstream builds: `libxev`, `libvaxis`, `zig-gamedev`, and
`tigerbeetle`.
Current Azazel benefit is reproducible toolchain/build diagnostics plus fork
metadata. Full build replacement is not claimed yet. Zaza is not inserted into
these pure-Zig upstream build graphs unless a repo has a C/C++ target slice that
we explicitly model.

Current executable Azazel parity slices:

| Project | Slice | Result | Boundary |
| --- | --- | --- | --- |
| `libxev` | `module:xev` plus `exe:xev_probe` | `ok` on Zig `0.16.0` | Proves import-mode module compilation through Azazel; full install graph is still future work. |
| `libvaxis` | `module:vaxis`, `exe:vaxis_probe`, `package:zigimg`, `package:uucode` | `zig-api-drift` on Zig `0.16.0` | Strict install-path parity now reaches `uucode`'s generated table builder and exposes the missing generated Unicode config surface; upstream still builds successfully. |
| `zig-gamedev` | `module:zig_gamedev_vectormath`, `exe:zig_gamedev_vectormath_probe`, `package:zmath`, `package:zopengl`, `package:zglfw`, `artifact:zglfw:glfw`, `package:zmesh`, `artifact:zmesh:zmesh`, `package:znoise`, `artifact:znoise:FastNoiseLite`, `package:zgui`, `artifact:zgui:imgui`, `package-option:zgui:backend=glfw_wgpu`, `package:zgpu`, `artifact:zgpu:zdawn`, `package-library-path:dawn_aarch64_macos`, `asset:sdl2_demo_content` | `ok` on Zig `0.15.2` | Proves a shared sample module, real Zig package dependencies, package-specific option forwarding, multiple native package artifact links including `zgui`'s backend-selected ImGui artifact and `zgpu`'s Dawn wrapper, package prebuilt library paths, and runtime asset staging can compile/install through Azazel; SDL/D3D/WebGPU full example selection is still future work. |

## Stable Lanes and Project-Required Toolchains

Two different things are called a Zig version in this corpus.

A stable lane is an Azazel property. `toolchain.zig.lanes` in `project.cue`
lists the `std.Build` API lanes the Azazel generator supports for that project:
`"0.14"`, `"0.15"`, `"0.16"`. The generated `build.zig` rejects any other lane.

A project-required toolchain is an upstream property. It is the Zig build the
project's own `build.zig` accepts. Each corpus manifest declares it under
`toolchain`, apart from `preferred_zig` and the overlay `project.cue` lanes.
There are three kinds:

| Kind | Accepts | Corpus example |
| --- | --- | --- |
| `exact` | one release, compared against `zig version` | Capy and TigerBeetle on `0.14.1` |
| `dev-window` | development builds from `min_version` (inclusive) up to `max_version` (exclusive) | ZLS: `>= 0.17.0-dev.292+fc1c83a36` and `< 0.17.0-dev.601+0ff175b69` |
| `custom` | a named build of another distribution, plus the version its `zig version` prints | Mach: `2026.4.10-mach`, which reports `0.16.0-dev.3142+5ccfeb926` |

The ZLS window comes from `minimum_zig_version` in its `build.zig.zon` and the
upper bound its `build.zig` enforces. The Mach name comes from
`mach_zig_version` in its `build.zig.zon`.

`tools/zig_toolchain.py` resolves a requirement in this order:

1. a configured path in `AZAZEL_ZIG_<ID>`, for example `AZAZEL_ZIG_017DEV` or
   `AZAZEL_ZIG_MACH2026410`
2. the local cache: every `*/zig` under `AZAZEL_TOOLCHAIN_ROOT`, then `~/zig`
3. `zig-<id>`, `zig-<version>` and `zig` on `PATH`
4. with `--fetch-toolchains` only: the official index at
   `ziglang.org/download/index.json`, the Mach index at
   `pkg.machengine.org/zig/index.json`, and known mirrors for official tarballs

Every candidate is run with `zig version` and compared with the requirement. A
configured path is checked the same way. A download is checked against the
index `shasum` before it is unpacked into the toolchain root. Without
`--fetch-toolchains` resolution stays offline.

`--doctor`, `--build` and `--executable-parity` report one of these when the
toolchain stops a run. The build is then never started and the repo is never
cloned.

| Classification | Meaning |
| --- | --- |
| `missing-toolchain` | No local binary satisfies the requirement. The diagnostic states the requirement and the override variable. |
| `unsupported-toolchain` | A binary configured for this requirement, or one from the same lane, is too old or too new. The diagnostic names the binary, its version and the accepted range. |
| `toolchain-fetch-failed` | `--fetch-toolchains` was given and no index or mirror could supply the build. The diagnostic lists each URL with its error. |

Each result carries a `toolchain` object with the requirement, every candidate
that was examined with its verdict, and every fetch attempt.

Checked on 2026-11-18 from a host with Zig `0.14.0` and `0.14.1` installed:

```text
$ tools/huge_corpus.py --build --repo zls
zls: build missing-toolchain (expected missing-toolchain)
  toolchain: requires Zig >= 0.17.0-dev.292+fc1c83a36 and < 0.17.0-dev.601+0ff175b69 ...

$ tools/huge_corpus.py --build --repo zls --fetch-toolchains
zls: build toolchain-fetch-failed (expected missing-toolchain)
  toolchain: ... fetch https://pkg.machengine.org/zig/index.json: no published build
  satisfies the requirement: 0.17.0-dev.892+54537285c is too new, ...
```

No index publishes a build inside the ZLS window any more, so the fetch names
the nearest builds and stops. With a too-new development build in the toolchain
root the same command reports `unsupported-toolchain`. `--fetch-toolchains` was
also used to install the official `0.16.0` release. The Mach download was not
run on this host.

## System Requirements

Each corpus manifest lists typed host requirements under `requirements`, in the
same shape as `#SystemDep` in `schema.cue`: `name`, `kind`, `os`, optional
`min_version` and `hint`. `--prepare` writes the same list into the overlay
`project.cue` as `system_deps`, so a repo's requirements are already Azazel
project data when a target slice is modeled.

River declares the tools `pkg-config` and `wayland-scanner` and the pkg-config
libraries `wayland-scanner`, `wayland-protocols`, `wayland-server`,
`wlroots-0.20`, `xkbcommon`, `pixman-1`, `libevdev` and `libinput`. libxev
declares `ws2_32` and `mswsock` as libraries on Windows only.

`--doctor` and `--build` probe tools with `PATH` and pkg-config libraries with
`pkg-config --exists`. Requirements whose `os` excludes the host are skipped.
Library, framework, header and include-directory requirements are recorded with
`checked: false`. Those need a compiler probe, which a generated Azazel build
runs through `zig build doctor`.

`--build` runs this preflight after the toolchain resolves and before cloning.
A missing requirement gives `system-dependency` from the manifest alone:

```text
$ tools/huge_corpus.py --build --repo river
river: build system-dependency (expected system-dependency)
  missing declared system requirement: tool wayland-scanner (not found on PATH); part of the wayland development package
  missing declared system requirement: pkg-config library wlroots-0.20 (not known to pkg-config)
  ...
```

The result carries a `system_requirements` object with one entry per
requirement: whether it applies on this host, whether it was checked, whether
it was found, and a detail line.

## Doctor Output

`tools/huge_corpus.py --doctor` answers "can this host run the declared proof
command?" without cloning or compiling. Useful statuses:

| Field | Meaning |
| --- | --- |
| `toolchain.found` | A local Zig binary satisfies the project-required toolchain. |
| `toolchain.status` | `found`, `missing-toolchain`, `unsupported-toolchain`, or `toolchain-fetch-failed`. |
| `toolchain.diagnostic` | The requirement, the binaries that were rejected and why, and how to supply one. |
| `required_tools` | Host commands such as `pkg-config` or `wayland-scanner`. |
| `requirements` | Every typed requirement with `applies`, `checked`, `found` and `detail`. |
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
| `tigerbeetle` | fails exact Zig requirement: expected `0.14.1`, host has `0.14.0` |
| `ghostty` | fails before graph execution on newer ZON/filesystem build APIs |

## Azazel Gaps Exposed

- Toolchain constraints: lane support exists for `0.14`, `0.15`, and `0.16`; corpus manifests now declare exact, dev-window and custom toolchains. `project.cue` itself still declares lanes only.
- Package dependencies: package module imports now exist, and executable corpus parity now covers local path dependencies; URL/hash fetch policy, lazy dependency options, and failure diagnostics still need richer modeling.
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
- Large repo support now has per-repo parity manifests and executable Azazel parity slices for `libxev`, `libvaxis`, and `zig-gamedev`; the next step is to expand slice coverage one repo at a time.

## Next Targets

1. Add enum/list build options.
2. Add URL/hash package dependency declarations and dependency-fetch diagnostics beyond local path parity.
3. Add generated-file/run-artifact output tracking.
4. Expand executable Azazel parity from module/package probes to library artifacts, tests, examples, and additional repos.
