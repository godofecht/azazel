// Shared, dependency-free helpers for running cue over an azazel package and
// turning its error text into structured problems. No vscode import here, so
// both the VS Code extension (extension.js) and the LSP prototype
// (../server/server.js) can require this one file.

'use strict';

const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');

// Names azazel expects in a build directory.
const SCHEMA = 'schema.cue';
const EXPORT = 'export.cue';

// Walk up from `startDir` until we find a directory that looks like an azazel
// build package (has both schema.cue and export.cue). Returns the directory or
// null. This is what lets diagnostics work whether the edited file is
// project.cue, export.cue, or schema.cue.
function findPackageDir(startDir) {
  let dir = startDir;
  for (let i = 0; i < 32; i++) {
    const hasSchema = fs.existsSync(path.join(dir, SCHEMA));
    const hasExport = fs.existsSync(path.join(dir, EXPORT));
    if (hasSchema && hasExport) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

// Run `cue export -e build` in `dir`. That is exactly what gen_build_spec.sh
// does, and it is the strictest cheap check: it resolves the whole `build`
// value, so it catches bad enums, wrong types, unknown fields, and missing
// required fields. Resolves to { code, output, spawnError } where output is
// stderr followed by stdout.
function runCue(cuePath, dir) {
  return new Promise((resolve) => {
    execFile(
      cuePath || 'cue',
      ['export', '-e', 'build'],
      { cwd: dir, timeout: 15000, maxBuffer: 4 * 1024 * 1024 },
      (err, stdout, stderr) => {
        const output = String(stderr || '') + String(stdout || '');
        // execFile sets err for a non-zero exit or a spawn failure. A spawn
        // failure (cue not on PATH) has err.code === 'ENOENT'.
        if (err && err.code === 'ENOENT') {
          resolve({ code: -1, output: '', spawnError: 'cue not found' });
          return;
        }
        resolve({ code: err ? err.code || 1 : 0, output });
      }
    );
  });
}

// Parse cue's diagnostic text into structured problems.
//
// cue prints a message line, optionally followed by indented location lines of
// the form `    ./file:line:col`. A single logical error can carry several
// locations. We keep the first location that is not schema.cue (which the user
// does not edit) so the squiggle lands on project.cue / export.cue where the
// real mistake is. Missing-field errors only ever point at schema.cue; those
// keep the schema location and the caller re-homes them onto the edited file.
//
// Returns [{ absPath, line, col, message }] with 1-based line/col.
function parseCueErrors(text, dir) {
  const lines = String(text).split('\n');
  const locRe = /^\s+(.+?):(\d+):(\d+)\s*$/;
  const problems = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim() || locRe.test(line)) {
      i++;
      continue;
    }
    // A message line. Strip a trailing colon that only introduces locations.
    const message = line.replace(/:\s*$/, '').trim();
    i++;

    const locs = [];
    while (i < lines.length) {
      const m = lines[i].match(locRe);
      if (!m) break;
      locs.push({ file: m[1], line: Number(m[2]), col: Number(m[3]) });
      i++;
    }
    if (locs.length === 0) continue; // header line; its children carry the locs

    const preferred =
      locs.find((l) => path.basename(l.file) !== SCHEMA) || locs[0];
    problems.push({
      absPath: path.resolve(dir, preferred.file),
      line: preferred.line,
      col: preferred.col,
      message,
    });
  }
  return problems;
}

module.exports = { findPackageDir, runCue, parseCueErrors, SCHEMA, EXPORT };
