// A symbol index for an azazel package, built by scanning project.cue and
// export.cue. Dependency-free, shared by the extension and the LSP server.
//
// It gives three things:
//   modules   every top-level `name: #Module` declaration and its position
//   deps      every string inside a `deps: [ ... ]` list, with its position
//             and the module it belongs to
//   exported  the set of names listed in export.cue's `_modules` map
//
// Positions are 0-based { line, character } to match LSP. The parser is
// line-based and deliberately simple: azazel declarations are flat.

'use strict';

const fs = require('fs');
const path = require('path');

// Match a top-level module declaration: `name: #Module`.
const DECL_RE = /^\s*([A-Za-z_]\w*)\s*:\s*#Module\b/;

function scanProject(text) {
  const modules = new Map(); // name -> { line, character }
  const deps = []; // { owner, name, line, character, endCharacter }
  const lines = text.split('\n');
  let currentOwner = null;

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];

    const decl = line.match(DECL_RE);
    if (decl) {
      const name = decl[1];
      const character = line.indexOf(name);
      modules.set(name, { line: li, character });
      currentOwner = name;
    }

    // Any `deps: [ "a", "b" ]` on this line: pull each quoted string with its
    // column. deps may span the same line as the declaration or a later line
    // inside the block; either way it belongs to the current module.
    if (/\bdeps\s*:/.test(line) || /^\s*"/.test(line)) {
      // Only treat quoted strings as deps when a deps list is in scope. A cheap
      // heuristic: the line contains `deps` or sits between `deps: [` and `]`.
      const stringRe = /"([^"]*)"/g;
      let m;
      while ((m = stringRe.exec(line)) !== null) {
        // Skip the module root string (root: "src/x.zig") and kind/link values.
        const before = line.slice(0, m.index);
        if (/\b(root|kind|profile|link)\s*:\s*$/.test(before.replace(/["']/g, ''))) {
          continue;
        }
        if (!/\bdeps\b/.test(line) && !inDepsBlock(lines, li)) continue;
        deps.push({
          owner: currentOwner,
          name: m[1],
          line: li,
          character: m.index + 1, // inside the quotes
          endCharacter: m.index + 1 + m[1].length,
        });
      }
    }
  }
  return { modules, deps };
}

// Is line `li` inside an open `deps: [` that has not been closed by `]`? Used
// for multi-line deps lists. Scans backward a few lines.
function inDepsBlock(lines, li) {
  for (let j = li; j >= 0 && j > li - 12; j--) {
    const l = lines[j];
    if (l.indexOf(']') !== -1 && j < li) return false;
    if (/\bdeps\s*:\s*\[/.test(l)) return l.indexOf(']') === -1 || j === li;
  }
  return false;
}

// Parse export.cue's `_modules: { "name": name, ... }` into a set of names.
function scanExport(text) {
  const exported = new Set();
  const start = text.indexOf('_modules');
  if (start === -1) return exported;
  const open = text.indexOf('{', start);
  if (open === -1) return exported;
  let depth = 0;
  let end = open;
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') {
      depth--;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = text.slice(open + 1, end);
  const re = /"([^"]+)"\s*:/g;
  let m;
  while ((m = re.exec(body)) !== null) exported.add(m[1]);
  return exported;
}

// Build the index for a package directory. `overrides` maps an absolute file
// path to unsaved buffer text, so the index reflects the editor, not disk.
function buildIndex(pkgDir, overrides) {
  overrides = overrides || {};
  const read = (name) => {
    const p = path.join(pkgDir, name);
    if (Object.prototype.hasOwnProperty.call(overrides, p)) return overrides[p];
    try {
      return fs.readFileSync(p, 'utf8');
    } catch (_e) {
      return '';
    }
  };
  const { modules, deps } = scanProject(read('project.cue'));
  const exported = scanExport(read('export.cue'));
  return { modules, deps, exported };
}

module.exports = { buildIndex, scanProject, scanExport };
