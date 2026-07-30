// Azazel VS Code extension.
//
// First increment: syntax awareness for .cue build files, inline diagnostics
// from cue on open and on save, and a command to run gen_build_spec.sh. The
// diagnostics run in-process here (no language server yet). The LSP that will
// eventually replace this in-process path is described in ../DESIGN.md and
// prototyped in ../server/server.js.

'use strict';

const vscode = require('vscode');
const cp = require('child_process');
const path = require('path');
const { findPackageDir, runCue, parseCueErrors } = require('./cueDiagnostics');

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

  if (result.code === 0) return; // clean

  const problems = parseCueErrors(result.output, pkgDir);
  const byFile = new Map();
  for (const p of problems) {
    // A missing-field error only carries a schema.cue location. Re-home it onto
    // the edited document so the user sees it where they can fix it.
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

  // Validate anything already open at activation.
  for (const doc of vscode.workspace.textDocuments) validateDocument(doc);
}

function deactivate() {
  if (diagnostics) diagnostics.dispose();
}

module.exports = { activate, deactivate };
