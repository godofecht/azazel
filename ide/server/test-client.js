#!/usr/bin/env node
// Smoke test for server.js. Spawns the server, runs the LSP handshake, opens
// project.cue, and exercises diagnostics, completion, hover, and definition.
// No test framework, no dependencies.
//
//   node server/test-client.js [packageDir]
//
// packageDir defaults to azazel's example 03-services. Point it at a directory
// with a broken project.cue to see cue errors and cross-checks flow through.

'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const pkgDir = path.resolve(
  process.argv[2] || path.join(__dirname, '..', '..', 'examples', '03-services')
);
const projectFile = path.join(pkgDir, 'project.cue');
const uri = 'file://' + projectFile.split(path.sep).map(encodeURIComponent).join('/');
const text = fs.readFileSync(projectFile, 'utf8');
const lines = text.split('\n');

// Positions to probe, derived from the file so this works on any package.
const kindLine = lines.findIndex((l) => /kind:\s*"/.test(l));
const kindValuePos = { line: kindLine, character: lines[kindLine].indexOf('"') + 1 };
const kindWordPos = { line: kindLine, character: lines[kindLine].indexOf('kind') + 1 };
let depsPos = null;
for (let i = 0; i < lines.length; i++) {
  const m = lines[i].match(/deps:\s*\[\s*"([^"]+)"/);
  if (m) {
    depsPos = { line: i, character: lines[i].indexOf('"' + m[1]) + 1 };
    break;
  }
}

const server = cp.spawn('node', [path.join(__dirname, 'server.js')], {
  stdio: ['pipe', 'pipe', 'inherit'],
});

let buf = Buffer.alloc(0);
server.stdout.on('data', (chunk) => {
  buf = Buffer.concat([buf, chunk]);
  for (;;) {
    const he = buf.indexOf('\r\n\r\n');
    if (he === -1) break;
    const m = buf.slice(0, he).toString().match(/Content-Length:\s*(\d+)/i);
    if (!m) break;
    const len = Number(m[1]);
    const start = he + 4;
    if (buf.length < start + len) break;
    const body = JSON.parse(buf.slice(start, start + len).toString('utf8'));
    buf = buf.slice(start + len);
    onMessage(body);
  }
});

function onMessage(body) {
  if (body.method === 'textDocument/publishDiagnostics') {
    const p = body.params;
    const file = decodeURIComponent(p.uri.replace('file://', ''));
    if (p.diagnostics.length === 0) {
      console.log(`diagnostics clean: ${path.basename(file)}`);
    } else {
      for (const d of p.diagnostics) {
        const sev = d.severity === 1 ? 'error' : 'warn';
        console.log(`${sev}: ${path.basename(file)}:${d.range.start.line + 1}  ${d.message}`);
      }
    }
  } else if (body.id === 1) {
    console.log('initialize ok:', JSON.stringify(body.result.serverInfo), 'caps:', Object.keys(body.result.capabilities).join(','));
  } else if (body.id === 3) {
    console.log('completion (after kind:):', body.result.items.map((i) => i.label).join(', '));
  } else if (body.id === 4) {
    console.log('hover (on kind):', body.result ? JSON.stringify(body.result.contents.value.split('\n')[0]) : 'null');
  } else if (body.id === 5) {
    const r = body.result;
    console.log('definition (deps entry):', r ? `${path.basename(decodeURIComponent(r.uri.replace('file://', '')))}:${r.range.start.line + 1}` : 'null');
  }
}

function send(msg) {
  const payload = Buffer.from(JSON.stringify(msg), 'utf8');
  server.stdin.write(`Content-Length: ${payload.length}\r\n\r\n`);
  server.stdin.write(payload);
}

send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { initializationOptions: {} } });
send({ jsonrpc: '2.0', method: 'initialized', params: {} });
send({
  jsonrpc: '2.0',
  method: 'textDocument/didOpen',
  params: { textDocument: { uri, languageId: 'cue', version: 1, text } },
});

setTimeout(() => {
  send({ jsonrpc: '2.0', id: 3, method: 'textDocument/completion', params: { textDocument: { uri }, position: kindValuePos } });
  send({ jsonrpc: '2.0', id: 4, method: 'textDocument/hover', params: { textDocument: { uri }, position: kindWordPos } });
  if (depsPos) send({ jsonrpc: '2.0', id: 5, method: 'textDocument/definition', params: { textDocument: { uri }, position: depsPos } });
  setTimeout(() => {
    send({ jsonrpc: '2.0', id: 2, method: 'shutdown' });
    send({ jsonrpc: '2.0', method: 'exit' });
  }, 400);
}, 1800);
