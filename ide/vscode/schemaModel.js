// A model of the azazel #Module schema, read from schema.cue so it stays
// correct when the schema changes. Dependency-free, shared by the VS Code
// extension and the LSP server.
//
// It parses the enum disjunctions (#Kind, #Profile, #Link) and the #Module
// field list out of schema.cue text, and pairs them with a short prose table
// the server ships for hover. Only the field names, enum members, and defaults
// come from the file; the prose is here.

'use strict';

const fs = require('fs');
const path = require('path');

// Prose docs, keyed by field name and by enum value. Kept short: one line each.
const FIELD_DOCS = {
  kind: 'Output type. `exe`, `static`, or `shared`.',
  root: 'Root source file for the module.',
  deps: 'Modules this one depends on. A link edge whose mode is set by `link`.',
  profile: 'Optimization profile. `debug` or `release`. Default `debug`.',
  link:
    'How dependents consume this module. `abi` links a separate artifact over ' +
    'the C ABI; `import` merges it as a Zig module. Default `abi`. A `shared` ' +
    'module is forced to `abi`.',
};

const VALUE_DOCS = {
  exe: 'An executable. Lands in `zig-out/bin`.',
  static: 'A static library. Lands in `zig-out/lib` when linked over the ABI.',
  shared: 'A shared library (.dylib/.so). Always consumed over the ABI.',
  debug: 'Debug build. Maps to `.Debug`.',
  release: 'Release build. Maps to `.ReleaseFast`.',
  abi: 'Linked as a separate artifact over the C ABI (pub export fn / extern fn).',
  import: 'Merged into each dependent as a Zig module, reached with @import.',
};

// Field name -> which enum backs it, when it is an enum field.
const FIELD_ENUM = { kind: 'Kind', profile: 'Profile', link: 'Link' };

// Parse `#Name: "a" | "b" | "c"` disjunctions into { Name: [a, b, c] }.
function parseEnums(text) {
  const enums = {};
  const re = /#(\w+):\s*("[^\n]*)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const name = m[1];
    const members = (m[2].match(/"([^"]+)"/g) || []).map((s) => s.slice(1, -1));
    if (members.length) enums[name] = members;
  }
  return enums;
}

// Parse the field names declared inside the #Module block, with any default.
function parseFields(text) {
  const start = text.indexOf('#Module:');
  if (start === -1) return [];
  // Take the balanced { ... } after #Module:.
  const open = text.indexOf('{', start);
  if (open === -1) return [];
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
  const fields = [];
  const seen = new Set();
  // A field line looks like `name: <type>` at the block's top level. Skip the
  // nested `if kind == "shared" { ... }` guard.
  const re = /(^|\n)\s*([a-zA-Z_]\w*)\s*:/g;
  let m;
  while ((m = re.exec(body)) !== null) {
    const name = m[2];
    if (name === 'if' || seen.has(name)) continue;
    seen.add(name);
    let def;
    // Default is written as `| *<value>` on the same line.
    const lineEnd = body.indexOf('\n', m.index + m[0].length);
    const line = body.slice(m.index, lineEnd === -1 ? undefined : lineEnd);
    const dm = line.match(/\*\s*("?[^\s|}]+"?)/);
    if (dm) def = dm[1].replace(/"/g, '');
    fields.push({ name, default: def, enumName: FIELD_ENUM[name] || null });
  }
  return fields;
}

// Build the model from a schema.cue path. Returns null if the file is missing.
function loadSchemaModel(schemaPath) {
  let text;
  try {
    text = fs.readFileSync(schemaPath, 'utf8');
  } catch (_e) {
    return null;
  }
  const enums = parseEnums(text);
  const fields = parseFields(text);
  return {
    fields, // [{ name, default, enumName }]
    enums, // { Kind: [...], Profile: [...], Link: [...] }
    fieldDoc(name) {
      return FIELD_DOCS[name] || null;
    },
    valueDoc(value) {
      return VALUE_DOCS[value] || null;
    },
    // Enum members for a field, or null if the field is not an enum.
    valuesFor(fieldName) {
      const e = FIELD_ENUM[fieldName];
      return e && enums[e] ? enums[e] : null;
    },
  };
}

// Convenience: find schema.cue next to a package file and load it.
function loadForPackage(pkgDir) {
  return loadSchemaModel(path.join(pkgDir, 'schema.cue'));
}

module.exports = { loadSchemaModel, loadForPackage, FIELD_DOCS, VALUE_DOCS };
