# Azazel for VS Code

Authoring support for azazel `project.cue` build files. First increment:
syntax highlighting for the `#Module` shape, inline `cue` diagnostics on open
and on save, and a command to regenerate `build_spec.zig`.

## What it does

- **Syntax.** A CUE grammar (`source.cue`) highlights comments, strings,
  definitions like `#Module`, and the azazel fields (`kind`, `root`, `deps`,
  `profile`, `link`) and their enum values (`exe`, `static`, `shared`, `abi`,
  `import`, `debug`, `release`).
- **Diagnostics.** On opening or saving any `.cue` file that sits in an azazel
  package (a directory with both `schema.cue` and `export.cue`, found by walking
  up from the file), the extension runs `cue export -e build` and surfaces every
  error inline. That is the same command `gen_build_spec.sh` runs, so it catches
  bad enums, wrong types, unknown fields, and missing required fields. A
  missing-field error that CUE can only pin to `schema.cue` is re-homed onto
  line 1 of the file you are editing.
- **Command: `Azazel: Generate build_spec`.** Runs `gen_build_spec.sh` for the
  package that owns the active file and writes `build_spec.zig`. Output goes to
  the "Azazel" output channel.
- **Command: `Azazel: Validate project.cue`.** Forces a validation pass on the
  active file.

The diagnostics run in-process. They do not replace CUE's own language server;
they give azazel-aware feedback with no setup beyond having `cue` on PATH. The
plan to move this onto a real language server is in
[`../DESIGN.md`](../DESIGN.md), with a working prototype in
[`../server/`](../server/).

## Requirements

- VS Code 1.75 or newer.
- `cue` on your PATH (or set `azazel.cuePath`). Version 0.16 is what this was
  built against.
- `sh` and whatever `gen_build_spec.sh` needs (python3) for the generate
  command.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `azazel.cuePath` | `cue` | Path to the cue binary. |
| `azazel.validateOnSave` | `true` | Validate on open and save. |
| `azazel.genScript` | `gen_build_spec.sh` | Generator script name. |

## Run it from source (F5)

There is no build step. The extension is plain JavaScript with no npm
dependencies.

1. Open this folder (`azazel/ide/vscode`) in VS Code:
   `code azazel/ide/vscode`.
2. Press `F5` (Run > Start Debugging). VS Code opens a second window, the
   Extension Development Host, with the extension loaded.
3. In that window, open an azazel project, for example `azazel/examples/03-services`.
   Open `project.cue`. You should see `#Module` and the field names highlighted.
4. Break something, for example change `kind: "exe"` to `kind: "dylib"`, and
   save. A red squiggle appears on the value with the `cue` message. Fix it and
   save again; the squiggle clears.
5. Run the command: `Cmd/Ctrl+Shift+P` then `Azazel: Generate build_spec`.
   `build_spec.zig` is written next to `project.cue` and the "Azazel" output
   channel shows the result.

If `F5` offers a launch-target picker, choose "VS Code Extension Development".
No `.vscode/launch.json` is required; VS Code infers the launch from
`package.json` `main`.

## Package it (optional)

To produce a `.vsix`:

```sh
npm install -g @vscode/vsce
cd azazel/ide/vscode
vsce package
```

Then `code --install-extension azazel-0.1.0.vsix`.

## Layout

```
ide/vscode/
  package.json                manifest: language, grammar, commands, settings
  extension.js                activation, diagnostics, commands
  cueDiagnostics.js           runs cue, parses its errors (shared with the LSP)
  language-configuration.json comments, brackets, auto-closing
  syntaxes/cue.tmLanguage.json  the CUE + azazel grammar
  .vscodeignore
```
