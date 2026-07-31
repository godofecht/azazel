// Editor-agnostic language features for azazel .cue files. Pure functions over
// (schema model, symbol index, document text, cursor). The LSP server and the
// VS Code extension both call these, then adapt the plain results to their own
// protocol shapes, so the two never drift.

'use strict';

// Convert a 0-based { line, character } into an absolute offset in `text`.
function offsetAt(text, line, character) {
  let off = 0;
  let ln = 0;
  while (ln < line) {
    const nl = text.indexOf('\n', off);
    if (nl === -1) return text.length;
    off = nl + 1;
    ln++;
  }
  return Math.min(off + character, text.length);
}

// The #Module block enclosing `offset`, or null. Returns the block's inner text
// from its opening brace up to the cursor, used to see which fields are present.
function enclosingModuleBlock(text, offset) {
  const head = text.lastIndexOf('#Module', offset);
  if (head === -1) return null;
  const open = text.indexOf('{', head);
  if (open === -1 || open > offset) return null;
  // Match braces from `open`; the cursor must sit before the matching close.
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') {
      depth--;
      if (depth === 0) return i >= offset ? text.slice(open + 1, offset) : null;
    }
  }
  return text.slice(open + 1, offset); // unclosed block, still being typed
}

// Completion at the cursor. Returns [{ label, kind, detail, doc }] where kind is
// 'field' or 'value'. Empty when there is nothing useful to offer.
function completionAt(schema, text, line, character) {
  if (!schema) return [];
  const lineStart = offsetAt(text, line, 0);
  const cursor = offsetAt(text, line, character);
  const linePrefix = text.slice(lineStart, cursor);

  // Value position: right of `kind:`, `profile:`, or `link:`.
  const valueCtx = linePrefix.match(/\b(kind|profile|link)\s*:\s*"?([\w-]*)$/);
  if (valueCtx) {
    const members = schema.valuesFor(valueCtx[1]) || [];
    return members.map((v) => ({
      label: v,
      kind: 'value',
      detail: valueCtx[1],
      doc: schema.valueDoc(v),
    }));
  }

  // Field position: inside a #Module block, not already right of a `:`.
  if (/[:]\s*[^\s,}]*$/.test(linePrefix)) return [];
  const block = enclosingModuleBlock(text, cursor);
  if (block === null) return [];
  const present = new Set(
    (block.match(/(^|\n|,|{)\s*([a-zA-Z_]\w*)\s*:/g) || []).map((s) =>
      s.replace(/[^a-zA-Z_]\w*$/, '').match(/([a-zA-Z_]\w*)\s*:?$/) ? s.match(/([a-zA-Z_]\w*)\s*:/)[1] : ''
    )
  );
  return schema.fields
    .filter((f) => !present.has(f.name))
    .map((f) => ({
      label: f.name,
      kind: 'field',
      detail: f.default != null ? `default ${f.default}` : 'required',
      doc: schema.fieldDoc(f.name),
    }));
}

// The word (identifier-ish token) under the cursor, with its bounds.
function wordAt(text, offset) {
  const isWord = (c) => /[A-Za-z0-9_-]/.test(c);
  let s = offset;
  let e = offset;
  while (s > 0 && isWord(text[s - 1])) s--;
  while (e < text.length && isWord(text[e])) e++;
  return { word: text.slice(s, e), start: s, end: e };
}

// Hover at the cursor. Returns { markdown } or null.
function hoverAt(schema, text, line, character) {
  if (!schema) return null;
  const off = offsetAt(text, line, character);
  const { word, start } = wordAt(text, off);
  if (!word) return null;
  // A field name is followed by a colon.
  const after = text.slice(start + word.length).match(/^\s*:/);
  if (after && schema.fieldDoc(word)) {
    return { markdown: `**${word}**\n\n${schema.fieldDoc(word)}` };
  }
  // Otherwise an enum value.
  const vd = schema.valueDoc(word);
  if (vd) return { markdown: `**"${word}"**\n\n${vd}` };
  // A bare field name not followed by a colon (e.g. hovering the word) still
  // gets its field doc if it is one of the known fields.
  if (schema.fieldDoc(word)) {
    return { markdown: `**${word}**\n\n${schema.fieldDoc(word)}` };
  }
  return null;
}

// Go-to-definition for a deps string. Returns { line, character } of the target
// module declaration, or null. `index` must be built from the same buffer text.
function definitionAt(index, line, character) {
  if (!index) return null;
  for (const d of index.deps) {
    if (d.line === line && character >= d.character && character <= d.endCharacter) {
      const decl = index.modules.get(d.name);
      if (decl) return { line: decl.line, character: decl.character };
      return null;
    }
  }
  return null;
}

// The two graph cross-checks cue cannot do: a deps entry that names no module,
// and a module absent from export.cue's _modules map. Returns
// [{ line, character, endCharacter, message, severity }] with severity 'warning'.
function crossCheckDiagnostics(index) {
  if (!index) return [];
  const out = [];
  for (const d of index.deps) {
    if (d.name && !index.modules.has(d.name)) {
      out.push({
        line: d.line,
        character: d.character,
        endCharacter: d.endCharacter,
        severity: 'warning',
        message: `dependency "${d.name}" names no module declared in project.cue`,
      });
    }
  }
  // Only lint _modules when export.cue actually declared some, so a package
  // mid-edit with an empty map does not light up every module.
  if (index.exported.size > 0) {
    for (const [name, pos] of index.modules) {
      if (!index.exported.has(name)) {
        out.push({
          line: pos.line,
          character: pos.character,
          endCharacter: pos.character + name.length,
          severity: 'warning',
          message: `module "${name}" is missing from export.cue's _modules map, so it is not built`,
        });
      }
    }
  }
  return out;
}

module.exports = {
  offsetAt,
  completionAt,
  hoverAt,
  definitionAt,
  crossCheckDiagnostics,
};
