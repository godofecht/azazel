// Automated tests for the shared IDE feature layer: schemaModel, symbolIndex,
// and the pure feature functions. Zero dependencies, run with `node --test`.
//
// The manual test-client (../server/test-client.js) drives the whole LSP over
// stdio. These tests pin the units underneath it so a regression names the
// function that broke rather than surfacing as a failed round trip.

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');

const { loadForPackage } = require('./schemaModel');
const { buildIndex } = require('./symbolIndex');
const features = require('./features');

// A complete azazel package to read real schema, project, and export cue from.
const PKG = path.join(__dirname, '..', '..', 'examples', '03-services');

// --- schemaModel -----------------------------------------------------------

test('schema model reads the #Module fields with their defaults', () => {
  const schema = loadForPackage(PKG);
  assert.ok(schema, 'schema loaded');

  const byName = new Map(schema.fields.map((f) => [f.name, f]));
  assert.deepEqual(
    [...byName.keys()].sort(),
    ['deps', 'kind', 'link', 'profile', 'root']
  );

  // Required fields carry no default; the rest carry the schema's.
  assert.equal(byName.get('kind').default, undefined);
  assert.equal(byName.get('root').default, undefined);
  assert.equal(byName.get('profile').default, 'debug');
  assert.equal(byName.get('link').default, 'abi');
});

test('schema model resolves enum members per field', () => {
  const schema = loadForPackage(PKG);
  assert.deepEqual(schema.valuesFor('kind'), ['exe', 'static', 'shared']);
  assert.deepEqual(schema.valuesFor('profile'), ['debug', 'release']);
  assert.deepEqual(schema.valuesFor('link'), ['abi', 'import']);
  // A non-enum field has no member list.
  assert.equal(schema.valuesFor('root'), null);
  assert.equal(schema.valuesFor('deps'), null);
});

test('schema model returns prose for fields and values', () => {
  const schema = loadForPackage(PKG);
  assert.match(schema.fieldDoc('kind'), /Output type/);
  assert.match(schema.valueDoc('shared'), /shared library/i);
  assert.equal(schema.fieldDoc('nope'), null);
  assert.equal(schema.valueDoc('nope'), null);
});

test('schema model is null for a directory with no schema.cue', () => {
  assert.equal(loadForPackage(path.join(__dirname, 'does-not-exist')), null);
});

// --- symbolIndex -----------------------------------------------------------

test('symbol index finds every module declaration', () => {
  const index = buildIndex(PKG);
  assert.deepEqual(
    [...index.modules.keys()].sort(),
    ['codec', 'gateway', 'protocol', 'worker']
  );
  // Positions point at the real declaration lines (0-based).
  assert.equal(index.modules.get('protocol').line, 14);
  assert.equal(index.modules.get('gateway').line, 27);
});

test('symbol index records deps with their spans', () => {
  const index = buildIndex(PKG);
  // gateway declares deps: ["protocol", "codec"].
  const gatewayDeps = index.deps
    .filter((d) => d.line === 30)
    .map((d) => d.name)
    .sort();
  assert.deepEqual(gatewayDeps, ['codec', 'protocol']);
  for (const d of index.deps) {
    assert.ok(d.endCharacter > d.character, 'dep span is non-empty');
  }
});

test('symbol index reads the exported set from export.cue', () => {
  const index = buildIndex(PKG);
  for (const name of ['protocol', 'codec', 'gateway', 'worker']) {
    assert.ok(index.exported.has(name), `${name} is exported`);
  }
});

test('symbol index overrides let unsaved buffer text win over disk', () => {
  const projectPath = path.join(PKG, 'project.cue');
  const edited =
    'package build\n\n' +
    'solo: #Module & {\n\tkind: "exe"\n\troot: "src/solo.zig"\n}\n';
  const index = buildIndex(PKG, { [projectPath]: edited });
  assert.deepEqual([...index.modules.keys()], ['solo']);
});

// --- completion ------------------------------------------------------------

const schema = loadForPackage(PKG);

test('completion offers enum values right of kind:', () => {
  const text = 'app: #Module & {\n\tkind: \n}';
  const items = features.completionAt(schema, text, 1, 7);
  assert.deepEqual(
    items.map((i) => i.label),
    ['exe', 'static', 'shared']
  );
  assert.ok(items.every((i) => i.kind === 'value'));
});

test('completion offers link values right of link:', () => {
  const text = 'app: #Module & {\n\tlink: \n}';
  const items = features.completionAt(schema, text, 1, 7);
  assert.deepEqual(
    items.map((i) => i.label),
    ['abi', 'import']
  );
});

test('completion offers the missing fields inside a #Module block', () => {
  // kind and root already present; expect the other three offered.
  const text = 'app: #Module & {\n\tkind: "exe"\n\troot: "m.zig"\n\t\n}';
  const items = features.completionAt(schema, text, 3, 1);
  const labels = items.map((i) => i.label).sort();
  assert.deepEqual(labels, ['deps', 'link', 'profile']);
  assert.ok(items.every((i) => i.kind === 'field'));
});

test('completion is empty with no schema', () => {
  assert.deepEqual(features.completionAt(null, 'x', 0, 0), []);
});

// --- hover -----------------------------------------------------------------

test('hover on a field name returns its doc', () => {
  const text = 'app: #Module & {\n\tkind: "exe"\n}';
  const hover = features.hoverAt(schema, text, 1, 2);
  assert.ok(hover);
  assert.match(hover.markdown, /\*\*kind\*\*/);
  assert.match(hover.markdown, /Output type/);
});

test('hover on an enum value returns its meaning', () => {
  const text = 'app: #Module & {\n\tkind: "shared"\n}';
  const hover = features.hoverAt(schema, text, 1, 10);
  assert.ok(hover);
  assert.match(hover.markdown, /shared library/i);
});

test('hover on empty space is null', () => {
  assert.equal(features.hoverAt(schema, 'app: #Module & {\n\n}', 1, 0), null);
});

// --- definition ------------------------------------------------------------

test('definition jumps from a deps entry to the module declaration', () => {
  const index = buildIndex(PKG);
  // worker's deps: ["protocol"] sits on line 38 (0-based) in project.cue.
  const workerDep = index.deps.find(
    (d) => d.name === 'protocol' && d.line === 38
  );
  assert.ok(workerDep, 'found the worker->protocol dep');
  const def = features.definitionAt(
    index,
    workerDep.line,
    workerDep.character + 1
  );
  assert.deepEqual(def, index.modules.get('protocol'));
});

test('definition off a dep string is null', () => {
  const index = buildIndex(PKG);
  assert.equal(features.definitionAt(index, 0, 0), null);
});

// --- cross-checks ----------------------------------------------------------

test('a clean package produces no cross-check diagnostics', () => {
  const index = buildIndex(PKG);
  assert.deepEqual(features.crossCheckDiagnostics(index), []);
});

test('a deps entry naming no module is flagged', () => {
  const projectPath = path.join(PKG, 'project.cue');
  const edited =
    'package build\n\n' +
    'app: #Module & {\n\tkind: "exe"\n\troot: "m.zig"\n\tdeps: ["ghost"]\n}\n';
  const index = buildIndex(PKG, { [projectPath]: edited });
  const diags = features.crossCheckDiagnostics(index);
  const ghost = diags.find((d) => /ghost/.test(d.message));
  assert.ok(ghost, 'ghost dependency flagged');
  assert.equal(ghost.severity, 'warning');
});

test('a module absent from export.cue _modules is flagged', () => {
  const projectPath = path.join(PKG, 'project.cue');
  const exportPath = path.join(PKG, 'export.cue');
  const project =
    'package build\n\n' +
    'orphan: #Module & {\n\tkind: "exe"\n\troot: "o.zig"\n}\n';
  const exported = 'package build\n\n_modules: {\n\t"other": other\n}\n';
  const index = buildIndex(PKG, {
    [projectPath]: project,
    [exportPath]: exported,
  });
  const diags = features.crossCheckDiagnostics(index);
  const orphan = diags.find((d) => /orphan.*missing from export/.test(d.message));
  assert.ok(orphan, 'orphan module flagged');
  assert.equal(orphan.severity, 'warning');
});
