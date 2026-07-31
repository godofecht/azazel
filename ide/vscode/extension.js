// Azazel VS Code extension.
//
// Syntax awareness for .cue build files, inline diagnostics from cue plus the
// two graph cross-checks cue cannot do, a command to run gen_build_spec.sh, and
// language features: completion for #Module fields and enum values, hover, and
// go-to-definition from a deps entry to the module it names.
//
// The features run in-process here, sharing the exact schema model, symbol
// index, and feature logic with the LSP server (../server/server.js) through
// ./schemaModel.js, ./symbolIndex.js, and ./features.js, so the two never
// drift. The LSP is the portable path for other editors; see ../DESIGN.md.

'use strict';

const vscode = require('vscode');
const cp = require('child_process');
const path = require('path');
const { findPackageDir, runCue, parseCueErrors } = require('./cueDiagnostics');
const { loadForPackage } = require('./schemaModel');
const { buildIndex } = require('./symbolIndex');
const features = require('./features');

// Build a symbol index for the package owning `document`, with the document's
// current (possibly unsaved) text overriding disk.
function indexForDocument(pkgDir, document) {
  const overrides = {};
  if (document && document.uri.scheme === 'file') {
    overrides[document.uri.fsPath] = document.getText();
  }
  return buildIndex(pkgDir, overrides);
}

function schemaForDocument(document) {
  if (!document || document.uri.scheme !== 'file') return null;
  const pkgDir = findPackageDir(path.dirname(document.uri.fsPath));
  return pkgDir ? loadForPackage(pkgDir) : null;
}

let diagnostics;
let output;

function config() {
  return vscode.workspace.getConfiguration('azazel');
}

// Validate the azazel package that owns `document` and paint the results.
async function validateDocument(document) {
  if (!document || document.languageId !== 'cue') return;
  if (document.uri.scheme !== 'file') return;
  if (!config().get('validateOnSave', true)) return;

  const fileDir = path.dirname(document.uri.fsPath);
  const pkgDir = findPackageDir(fileDir);
  if (!pkgDir) {
    // Not an azazel package (no schema.cue + export.cue up the tree). Leave it
    // alone; this is a plain .cue file we have nothing authoritative to say on.
    return;
  }

  const cuePath = config().get('cuePath', 'cue');
  const result = await runCue(cuePath, pkgDir);

  if (result.spawnError) {
    output.appendLine(
      `[azazel] could not run '${cuePath}': ${result.spawnError}. ` +
        `Set azazel.cuePath or install cue.`
    );
    return;
  }

  // Clear diagnostics for the three files we might touch in this package, then
  // repaint from the fresh run.
  const owned = ['schema.cue', 'export.cue', 'project.cue'].map((n) =>
    vscode.Uri.file(path.join(pkgDir, n))
  );
  for (const uri of owned) diagnostics.delete(uri);

  const byFile = new Map();

  if (result.code !== 0) {
    const problems = parseCueErrors(result.output, pkgDir);
    for (const p of problems) {
      // A missing-field error only carries a schema.cue location. Re-home it
      // onto the edited document so the user sees it where they can fix it.
      let targetPath = p.absPath;
      let line = p.line;
      let col = p.col;
      if (path.basename(targetPath) === 'schema.cue') {
        targetPath = document.uri.fsPath;
        line = 1;
        col = 1;
      }
      const range = new vscode.Range(
        Math.max(0, line - 1),
        Math.max(0, col - 1),
        Math.max(0, line - 1),
        Math.max(0, col)
      );
      const diag = new vscode.Diagnostic(
        range,
        p.message,
        vscode.DiagnosticSeverity.Error
      );
      diag.source = 'azazel (cue)';
      if (!byFile.has(targetPath)) byFile.set(targetPath, []);
      byFile.get(targetPath).push(diag);
    }
  }

  const projectPath = path.join(pkgDir, 'project.cue');
  for (const p of features.crossCheckDiagnostics(indexForDocument(pkgDir, document))) {
    const range = new vscode.Range(
      p.line,
      p.character,
      p.line,
      p.endCharacter
    );
    const diag = new vscode.Diagnostic(
      range,
      p.message,
      vscode.DiagnosticSeverity.Warning
    );
    diag.source = 'azazel';
    if (!byFile.has(projectPath)) byFile.set(projectPath, []);
    byFile.get(projectPath).push(diag);
  }

  for (const [fsPath, diags] of byFile) {
    diagnostics.set(vscode.Uri.file(fsPath), diags);
  }
}

// Run gen_build_spec.sh for the package that owns the active file.
function generateBuildSpec() {
  const editor = vscode.window.activeTextEditor;
  const startDir = editor
    ? path.dirname(editor.document.uri.fsPath)
    : (vscode.workspace.workspaceFolders || [])[0]?.uri.fsPath;
  if (!startDir) {
    vscode.window.showErrorMessage('Azazel: no active file or workspace folder.');
    return;
  }
  const pkgDir = findPackageDir(startDir);
  if (!pkgDir) {
    vscode.window.showErrorMessage(
      'Azazel: no build package here (need schema.cue and export.cue).'
    );
    return;
  }
  const scriptName = config().get('genScript', 'gen_build_spec.sh');
  const scriptPath = path.join(pkgDir, scriptName);

  output.show(true);
  output.appendLine(`[azazel] running ${scriptPath}`);
  cp.execFile('sh', [scriptPath], { cwd: pkgDir }, (err, stdout, stderr) => {
    if (stdout) output.appendLine(stdout.trimEnd());
    if (stderr) output.appendLine(stderr.trimEnd());
    if (err) {
      vscode.window.showErrorMessage(`Azazel: generate failed. See output.`);
    } else {
      vscode.window.showInformationMessage('Azazel: build_spec.zig generated.');
    }
  });
}

function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection('azazel');
  output = vscode.window.createOutputChannel('Azazel');
  context.subscriptions.push(diagnostics, output);

  context.subscriptions.push(
    vscode.commands.registerCommand('azazel.generateBuildSpec', generateBuildSpec),
    vscode.commands.registerCommand('azazel.validate', () => {
      const ed = vscode.window.activeTextEditor;
      if (ed) validateDocument(ed.document);
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => validateDocument(doc)),
    vscode.workspace.onDidOpenTextDocument((doc) => validateDocument(doc)),
    vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri))
  );

  const cueSelector = { language: 'cue', scheme: 'file' };
  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(
      cueSelector,
      {
        provideCompletionItems(document, position) {
          const schema = schemaForDocument(document);
          return features
            .completionAt(schema, document.getText(), position.line, position.character)
            .map((item) => {
              const completion = new vscode.CompletionItem(
                item.label,
                item.kind === 'field'
                  ? vscode.CompletionItemKind.Field
                  : vscode.CompletionItemKind.EnumMember
              );
              completion.detail = item.detail;
              if (item.doc) completion.documentation = new vscode.MarkdownString(item.doc);
              return completion;
            });
        },
      },
      '"',
      ':',
      ' '
    ),
    vscode.languages.registerHoverProvider(cueSelector, {
      provideHover(document, position) {
        const schema = schemaForDocument(document);
        const hover = features.hoverAt(
          schema,
          document.getText(),
          position.line,
          position.character
        );
        return hover ? new vscode.Hover(new vscode.MarkdownString(hover.markdown)) : null;
      },
    }),
    vscode.languages.registerDefinitionProvider(cueSelector, {
      provideDefinition(document, position) {
        if (document.uri.scheme !== 'file') return null;
        const pkgDir = findPackageDir(path.dirname(document.uri.fsPath));
        if (!pkgDir) return null;
        const def = features.definitionAt(
          indexForDocument(pkgDir, document),
          position.line,
          position.character
        );
        if (!def) return null;
        const uri = vscode.Uri.file(path.join(pkgDir, 'project.cue'));
        const pos = new vscode.Position(def.line, def.character);
        return new vscode.Location(uri, pos);
      },
    })
  );

  // Validate anything already open at activation.
  for (const doc of vscode.workspace.textDocuments) validateDocument(doc);
}

function deactivate() {
  if (diagnostics) diagnostics.dispose();
}

module.exports = { activate, deactivate };
