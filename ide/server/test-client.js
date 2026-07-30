#!/usr/bin/env node
// Smoke test for server.js. Spawns the server, runs the LSP handshake, opens a
// couple of .cue documents, and prints the diagnostics the server pushes back.
// No test framework, no dependencies.
//
//   node server/test-client.js [packageDir]
//
// packageDir defaults to azazel's example 03-services. Point it at a directory
// that has a broken project.cue to see real cue errors flow through.

'use strict';

const cp = require('child_process');
const path = require('path');

const pkgDir = path.resolve(
  process.argv[2] || path.join(__dirname, '..', '..', 'examples', '03-services')
);
const projectFile = path.join(pkgDir, 'project.cue');
const uri = 'file://' + projectFile.split(path.sep).map(encodeURIComponent).join('/');

const server = cp.spawn('node', [path.join(__dirname, 'server.js')], {
  stdio: ['pipe', 'pipe', 'inherit'],
});

let buf = Buffer.alloc(0);
let got = 0;
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
    if (body.method === 'textDocument/publishDiagnostics') {
      got++;
      const p = body.params;
      const file = decodeURIComponent(p.uri.replace('file://', ''));
      if (p.diagnostics.length === 0) {
        console.log(`clean: ${path.basename(file)}`);
      } else {
        for (const d of p.diagnostics) {
          console.log(
            `error: ${path.basename(file)}:${d.range.start.line + 1}:${
              d.range.start.character + 1
            }  ${d.message}`
          );
        }
      }
    }
    if (body.id === 1) {
      console.log('initialize ok:', JSON.stringify(body.result.serverInfo));
    }
  }
});

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
  params: { textDocument: { uri, languageId: 'cue', version: 1, text: '' } },
});

// Give cue time to run, then shut down cleanly.
setTimeout(() => {
  send({ jsonrpc: '2.0', id: 2, method: 'shutdown' });
  send({ jsonrpc: '2.0', method: 'exit' });
  console.log(`\nreceived ${got} publishDiagnostics notification(s)`);
}, 2500);
