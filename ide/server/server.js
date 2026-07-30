#!/usr/bin/env node
// azazel-lsp: a minimal Language Server Protocol prototype.
//
// This is a working prototype, not the finished server. It speaks LSP over
// stdio with zero npm dependencies (raw JSON-RPC framing) and does one useful
// thing: publish cue diagnostics for azazel .cue files on open, change, and
// save. The full design, including completion, hover, and go-to-definition,
// lives in ../DESIGN.md. The diagnostic engine is shared with the VS Code
// extension via ../vscode/cueDiagnostics.js so the two never drift.
//
// Try it without an editor:
//   node server/test-client.js
//
// Wire it into an editor by pointing an LSP client at:
//   node /abs/path/to/ide/server/server.js  (transport: stdio)

'use strict';

const path = require('path');
const {
  findPackageDir,
  runCue,
  parseCueErrors,
} = require('../vscode/cueDiagnostics');

let cuePath = 'cue';

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
      // Unrecoverable framing; drop what we have.
      buffer = Buffer.alloc(0);
      return;
    }
    const len = Number(m[1]);
    const start = headerEnd + 4;
    if (buffer.length < start + len) return; // wait for more bytes
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
  const json = JSON.stringify(msg);
  const payload = Buffer.from(json, 'utf8');
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
  // file:///Users/... -> /Users/...  (drop the empty authority)
  if (p.startsWith('/') === false) p = '/' + p;
  return p;
}

function pathToUri(p) {
  const abs = path.resolve(p);
  return 'file://' + abs.split(path.sep).map(encodeURIComponent).join('/').replace('file%3A', 'file:');
}

// ---- diagnostics ----------------------------------------------------------

async function publishDiagnostics(uri) {
  const fsPath = uriToPath(uri);
  const pkgDir = findPackageDir(path.dirname(fsPath));
  if (!pkgDir) {
    notify('textDocument/publishDiagnostics', { uri, diagnostics: [] });
    return;
  }
  const result = await runCue(cuePath, pkgDir);
  if (result.spawnError) {
    process.stderr.write(`[azazel-lsp] ${result.spawnError}\n`);
    return;
  }

  // Group by file, then publish per file. Clear the just-edited file first so a
  // now-clean document loses its old squiggles.
  const perFile = new Map();
  perFile.set(fsPath, []);

  if (result.code !== 0) {
    for (const p of parseCueErrors(result.output, pkgDir)) {
      let targetPath = p.absPath;
      let line = p.line;
      let col = p.col;
      if (path.basename(targetPath) === 'schema.cue') {
        targetPath = fsPath; // re-home missing-field errors onto the edited doc
        line = 1;
        col = 1;
      }
      const d = {
        range: {
          start: { line: Math.max(0, line - 1), character: Math.max(0, col - 1) },
          end: { line: Math.max(0, line - 1), character: Math.max(0, col) },
        },
        severity: 1, // Error
        source: 'azazel (cue)',
        message: p.message,
      };
      if (!perFile.has(targetPath)) perFile.set(targetPath, []);
      perFile.get(targetPath).push(d);
    }
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
        (params &&
          params.initializationOptions &&
          params.initializationOptions.cuePath) ||
        'cue';
      reply(id, {
        capabilities: {
          // Full-content sync keeps the prototype simple: cue reads from disk,
          // so we act on save/open. incremental sync is a later optimisation.
          textDocumentSync: 1,
        },
        serverInfo: { name: 'azazel-lsp', version: '0.1.0' },
      });
      break;

    case 'initialized':
      break;

    case 'textDocument/didOpen':
    case 'textDocument/didSave':
    case 'textDocument/didChange':
      if (params && params.textDocument && params.textDocument.uri) {
        publishDiagnostics(params.textDocument.uri);
      }
      break;

    case 'textDocument/didClose':
      if (params && params.textDocument && params.textDocument.uri) {
        notify('textDocument/publishDiagnostics', {
          uri: params.textDocument.uri,
          diagnostics: [],
        });
      }
      break;

    case 'shutdown':
      reply(id, null);
      break;

    case 'exit':
      process.exit(0);
      break;

    default:
      // Unknown request: answer with a method-not-found error so clients that
      // wait on a response do not hang.
      if (id !== undefined) {
        send({
          jsonrpc: '2.0',
          id,
          error: { code: -32601, message: `method not found: ${method}` },
        });
      }
  }
}

process.stderr.write('[azazel-lsp] started, waiting on stdio\n');
