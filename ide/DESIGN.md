# Azazel language server: design

The VS Code extension in [`vscode/`](vscode/) covers the first increment with
in-process diagnostics. This document describes the language server that will
carry the richer features, and the prototype that already exists in
[`server/`](server/).

## Why a server

Diagnostics alone can live inside one editor extension. Completion, hover, and
go-to-definition should not, for two reasons. They need a live model of the
`schema.cue` shape and the module graph, and that model is worth building once
and reusing across editors. LSP is the portable boundary: the same server
answers Neovim, Helix, Zed, and VS Code.

The server owns everything azazel-specific. The editor side stays a thin client
that starts the process and forwards requests.

## Scope

Four features, in priority order.

1. **Diagnostics** from `cue`. Already prototyped. Run `cue export -e build` in
   the package directory, parse the errors, publish them per file. This is the
   same engine the extension uses, shared through
   [`vscode/cueDiagnostics.js`](vscode/cueDiagnostics.js).
2. **Completion** for `#Module` fields and their enum values.
3. **Hover** documentation for fields and enum values.
4. **Go-to-definition** from a `deps` entry to the module that declares it.

### Completion

Two contexts, both derivable without a full CUE parser for the first cut.

- Inside a `#Module & { ... }` block, offer the field names: `kind`, `root`,
  `deps`, `profile`, `link`. Skip fields already present in the block.
- On the right of `kind:`, `profile:`, or `link:`, offer the enum members for
  that field: `kind` gives `exe`/`static`/`shared`, `profile` gives
  `debug`/`release`, `link` gives `abi`/`import`.

The field list and the enum members are read from `schema.cue` so the server
stays correct when the schema changes. `cue export schema.cue` renders the
definitions as JSON; the disjunction for `#Kind`, `#Profile`, and `#Link` gives
the enum members, and the fields of `#Module` give the field names and their
defaults. Parse that once per workspace, refresh when `schema.cue` changes.

Completion detail can carry the default, for example `profile` completes with
detail `debug`, and `link` notes that `shared` forces `abi`.

### Hover

Hover reuses the same schema model plus a short prose table the server ships:

- `kind`: output type. `exe`, `static`, or `shared`.
- `root`: root source file for the module.
- `deps`: modules this one depends on. A link edge whose mode is set by `link`.
- `profile`: `debug` or `release`. Default `debug`.
- `link`: how dependents consume this module. `abi` links a separate artifact
  over the C ABI; `import` merges it as a Zig module. Default `abi`. `shared`
  forces `abi`.

Hovering an enum value shows that value's one-line meaning, taken from the
comments already in `schema.cue`.

### Go-to-definition

In azazel a dependency is a string: `deps: ["core"]`. Definition resolves that
string to the top-level field `core: #Module & { ... }` in `project.cue`.

The server keeps a symbol index per package: every top-level `#Module`
declaration and its position. On a definition request, if the cursor sits inside
a string literal within a `deps` list, look the string up in the index and
return the declaration's location. The same index powers a diagnostic the schema
cannot give on its own: a `deps` entry that names no module, and a module absent
from `export.cue`'s `_modules` map (the two documented gotchas). CUE does not
catch either, so the server should.

## Architecture

```
editor  <--LSP/stdio-->  azazel-lsp
                            |
                            +-- diagnostics:  cue export -e build   (done)
                            +-- schema model: cue export schema.cue (planned)
                            +-- symbol index: scan project.cue      (planned)
```

State the server holds per workspace:

- `schemaModel`: fields, enum members, defaults, parsed from `schema.cue`.
- `symbolIndex`: module name to declaration range, per package directory.
- open document text, for completion and definition on unsaved buffers.

Both derived structures invalidate on save of `schema.cue`, `project.cue`, or
`export.cue`.

## Transport and dependencies

The prototype speaks LSP over stdio with raw JSON-RPC framing and no npm
dependencies. That keeps it self-contained and easy to vendor. If the feature
set grows, the natural next step is `vscode-languageserver` for the protocol
plumbing and `vscode-languageclient` on the extension side. The trade is a build
step and a `node_modules`. Hold that until completion and definition are real;
the raw approach is enough for diagnostics.

For the CUE side, two options:

- **Shell out to `cue`** (current). Simple, always matches the user's cue
  version, one process per validation. Good enough at this scale.
- **CUE's Go API or an LSP from the CUE project.** Lower latency, a real syntax
  tree, incremental parsing. More weight. Revisit if shelling out shows lag on
  large projects.

## Prototype

[`server/server.js`](server/server.js) is a runnable server. It handles
`initialize`, `initialized`, `textDocument/didOpen`, `didChange`, `didSave`,
`didClose`, `shutdown`, and `exit`, and it publishes cue diagnostics. It shares
the diagnostic engine with the extension.

Run the smoke test, which spawns the server, runs the handshake, opens a
document, and prints what the server pushes back:

```sh
node server/test-client.js /path/to/azazel/examples/03-services   # clean
node server/test-client.js /path/to/a/broken/package              # errors
```

Point any LSP client at `node ide/server/server.js` over stdio to use it in an
editor today, with diagnostics only. Completion, hover, and definition are the
next commits against the plan above.

## Status

| Feature | State |
|---|---|
| Diagnostics from cue | prototyped, shared with the extension |
| LSP handshake and lifecycle | prototyped |
| Completion (fields, enums) | designed |
| Hover | designed |
| Go-to-definition for deps | designed |
| deps / export.cue cross-checks | designed |
