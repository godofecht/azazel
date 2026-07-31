#!/usr/bin/env node
// azazel-lsp: a Language Server Protocol server for authoring project.cue.
//
// Speaks LSP over stdio with zero npm dependencies (raw JSON-RPC framing). It
// serves:
//   - diagnostics from `cue export -e build`, on open/change/save
//   - the two graph cross-checks cue cannot do (a dep naming no module, a module
//     missing from export.cue's _modules)
//   - completion for #Module fields and their enum values
//   - hover for fields and enum values
//   - go-to-definition from a deps entry to the module it names
//
// The schema model, symbol index, and feature logic are shared with the VS Code
// extension via ../vscode/*.js so the two never drift. Full design in
// ../DESIGN.md.
//
// Try it without an editor:
//   node server/test-client.js
// Wire it into an editor by pointing an LSP client at:
//   node /abs/path/to/ide/server/server.js  (transport: stdio)

'use strict';

const path = require('path');
const fs = require('fs');
const { findPackageDir, runCue, parseCueErrors } = require('../vscode/cueDiagnostics');
const { loadForPackage } = require('../vscode/schemaModel');
const { buildIndex } = require('../vscode/symbolIndex');
const features = require('../vscode/features');

let cuePath = 'cue';
const docs = new Map(); // fsPath -> current text (open buffers)

// ---- JSON-RPC framing over stdio -----------------------------------------

let buffer = Buffer.alloc(0);

process.stdin.on('data', (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  drain();
});

function drain() {
  for (;;) {
    const headerEnd = buffer.indexOf('\r\n\r\n');
    if (headerEnd === -1) return;
    const header = buffer.slice(0, headerEnd).toString('ascii');
    const m = header.match(/Content-Length:\s*(\d+)/i);
    if (!m) {
      buffer = Buffer.alloc(0);
      return;
    }
    const len = Number(m[1]);
    const start = headerEnd + 4;
    if (buffer.length < start + len) return;
    const body = buffer.slice(start, start + len).toString('utf8');
    buffer = buffer.slice(start + len);
    let msg;
    try {
      msg = JSON.parse(body);
    } catch (_e) {
      continue;
    }
    handle(msg);
  }
}

function send(msg) {
  const payload = Buffer.from(JSON.stringify(msg), 'utf8');
  process.stdout.write(`Content-Length: ${payload.length}\r\n\r\n`);
  process.stdout.write(payload);
}

function reply(id, result) {
  send({ jsonrpc: '2.0', id, result });
}

function notify(method, params) {
  send({ jsonrpc: '2.0', method, params });
}

// ---- URI helpers ----------------------------------------------------------

function uriToPath(uri) {
  if (!uri.startsWith('file://')) return uri;
  let p = decodeURIComponent(uri.slice('file://'.length));
  if (p.startsWith('/') === false) p = '/' + p;
  return p;
}

function pathToUri(p) {
  const abs = path.resolve(p);
  return 'file://' + abs.split(path.sep).map(encodeURIComponent).join('/').replace('file%3A', 'file:');
}

// Text for a path: the open buffer if we have it, else disk.
function textFor(fsPath) {
  if (docs.has(fsPath)) return docs.get(fsPath);
  try {
    return fs.readFileSync(fsPath, 'utf8');
  } catch (_e) {
    return '';
  }
}

// A symbol index for the package, with every open buffer overriding disk.
function indexFor(pkgDir) {
  const overrides = {};
  for (const [p, t] of docs) overrides[p] = t;
  return buildIndex(pkgDir, overrides);
}

// ---- diagnostics ----------------------------------------------------------

async function publishDiagnostics(uri) {
  const fsPath = uriToPath(uri);
  const pkgDir = findPackageDir(path.dirname(fsPath));
  if (!pkgDir) {
    notify('textDocument/publishDiagnostics', { uri, diagnostics: [] });
    return;
  }

  const perFile = new Map();
  perFile.set(fsPath, []);
  const projectPath = path.join(pkgDir, 'project.cue');
  perFile.set(projectPath, []); // always refresh cross-checks on project.cue

  // cue diagnostics.
  const result = await runCue(cuePath, pkgDir);
  if (result.spawnError) {
    process.stderr.write(`[azazel-lsp] ${result.spawnError}\n`);
  } else if (result.code !== 0) {
    for (const p of parseCueErrors(result.output, pkgDir)) {
      let targetPath = p.absPath;
      let line = p.line;
      let col = p.col;
      if (path.basename(targetPath) === 'schema.cue') {
        targetPath = fsPath;
        line = 1;
        col = 1;
      }
      const d = {
        range: {
          start: { line: Math.max(0, line - 1), character: Math.max(0, col - 1) },
          end: { line: Math.max(0, line - 1), character: Math.max(0, col) },
        },
        severity: 1,
        source: 'azazel (cue)',
        message: p.message,
      };
      if (!perFile.has(targetPath)) perFile.set(targetPath, []);
      perFile.get(targetPath).push(d);
    }
  }

  // The two graph cross-checks, from the symbol index.
  for (const c of features.crossCheckDiagnostics(indexFor(pkgDir))) {
    perFile.get(projectPath).push({
      range: {
        start: { line: c.line, character: c.character },
        end: { line: c.line, character: c.endCharacter },
      },
      severity: c.severity === 'warning' ? 2 : 1,
      source: 'azazel',
      message: c.message,
    });
  }

  for (const [fp, diags] of perFile) {
    notify('textDocument/publishDiagnostics', { uri: pathToUri(fp), diagnostics: diags });
  }
}

// ---- request routing ------------------------------------------------------

function handle(msg) {
  const { id, method, params } = msg;
  switch (method) {
    case 'initialize':
      cuePath =
        (params && params.initializationOptions && params.initializationOptions.cuePath) || 'cue';
      reply(id, {
        capabilities: {
          textDocumentSync: 1,
          completionProvider: { triggerCharacters: ['"', ':', ' '] },
          hoverProvider: true,
          definitionProvider: true,
        },
        serverInfo: { name: 'azazel-lsp', version: '0.2.0' },
      });
      break;

    case 'initialized':
      break;

    case 'textDocument/didOpen':
      if (params && params.textDocument) {
        docs.set(uriToPath(params.textDocument.uri), params.textDocument.text || '');
        publishDiagnostics(params.textDocument.uri);
      }
      break;

    case 'textDocument/didChange':
      if (params && params.textDocument) {
        const fsPath = uriToPath(params.textDocument.uri);
        const changes = params.contentChanges || [];
        if (changes.length) docs.set(fsPath, changes[changes.length - 1].text);
        publishDiagnostics(params.textDocument.uri);
      }
      break;

    case 'textDocument/didSave':
      if (params && params.textDocument) publishDiagnostics(params.textDocument.uri);
      break;

    case 'textDocument/didClose':
      if (params && params.textDocument) {
        docs.delete(uriToPath(params.textDocument.uri));
        notify('textDocument/publishDiagnostics', {
          uri: params.textDocument.uri,
          diagnostics: [],
        });
      }
      break;

    case 'textDocument/completion': {
      const fsPath = uriToPath(params.textDocument.uri);
      const pkgDir = findPackageDir(path.dirname(fsPath));
      const schema = pkgDir ? loadForPackage(pkgDir) : null;
      const items = features
        .completionAt(schema, textFor(fsPath), params.position.line, params.position.character)
        .map((c) => ({
          label: c.label,
          kind: c.kind === 'field' ? 5 : 20, // Field / EnumMember
          detail: c.detail,
          documentation: c.doc ? { kind: 'markdown', value: c.doc } : undefined,
        }));
      reply(id, { isIncomplete: false, items });
      break;
    }

    case 'textDocument/hover': {
      const fsPath = uriToPath(params.textDocument.uri);
      const pkgDir = findPackageDir(path.dirname(fsPath));
      const schema = pkgDir ? loadForPackage(pkgDir) : null;
      const h = features.hoverAt(schema, textFor(fsPath), params.position.line, params.position.character);
      reply(id, h ? { contents: { kind: 'markdown', value: h.markdown } } : null);
      break;
    }

    case 'textDocument/definition': {
      const fsPath = uriToPath(params.textDocument.uri);
      const pkgDir = findPackageDir(path.dirname(fsPath));
      if (!pkgDir) {
        reply(id, null);
        break;
      }
      const def = features.definitionAt(indexFor(pkgDir), params.position.line, params.position.character);
      if (!def) {
        reply(id, null);
        break;
      }
      reply(id, {
        uri: pathToUri(path.join(pkgDir, 'project.cue')),
        range: {
          start: { line: def.line, character: def.character },
          end: { line: def.line, character: def.character },
        },
      });
      break;
    }

    case 'shutdown':
      reply(id, null);
      break;

    case 'exit':
      process.exit(0);
      break;

    default:
      if (id !== undefined) {
        send({ jsonrpc: '2.0', id, error: { code: -32601, message: `method not found: ${method}` } });
      }
  }
}

process.stderr.write('[azazel-lsp] started, waiting on stdio\n');
