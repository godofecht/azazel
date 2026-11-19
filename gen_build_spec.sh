#!/bin/sh
# Generate build_spec.zig from CUE definitions.
# No JSON runtime — CUE exports directly to Zig source.
set -e

cd "$(dirname "$0")"

# Memoize the codegen. build_spec.zig is a pure function of the CUE inputs and
# this script, so on an unchanged model there is nothing to regenerate: hash the
# inputs and skip the whole cue + codegen step when it matches the last run.
# This makes the data layer free on every rebuild but the first.
STAMP=".build_spec.stamp"
SIG=$(cat schema.cue project.cue export.cue gen_build_spec.sh 2>/dev/null | shasum | cut -d' ' -f1)
if [ -f build_spec.zig ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$SIG" ]; then
    exit 0
fi

DATA=$(cue export -e build)

cat > build_spec.zig <<'HEADER'
const std = @import("std");

pub const Kind = enum { exe, static, shared, module };
pub const Link = enum { abi, import };
pub const OptionType = enum { bool, string, u32 };

pub const Command = struct {
    argv: []const []const u8,
};

pub const InstallDir = struct {
    source_dir: []const u8,
    install_dir: []const u8,
    install_subdir: []const u8,
};

pub const PackageLibraryPath = struct {
    package: []const u8,
    path: []const u8,
    os: ?[]const u8,
    arch: ?[]const u8,
};

pub const Toolchain = struct {
    zig_lanes: []const []const u8,
    preferred_zig_lane: []const u8,
};

pub const Package = struct {
    name: []const u8,
    url: ?[]const u8,
    hash: ?[]const u8,
    path: ?[]const u8,
    lazy: bool,
};

pub const Option = struct {
    name: []const u8,
    type: OptionType,
    description: []const u8,
    bool_default: ?bool,
    string_default: ?[]const u8,
    u32_default: ?u32,
};

pub const SystemDepKind = enum { tool, pkg_config, library, framework, header, include_dir };

pub const SystemDep = struct {
    name: []const u8,
    kind: SystemDepKind,
    os: []const []const u8,
    min_version: ?[]const u8,
    hint: []const u8,
};

pub const PackageImport = struct {
    alias: []const u8,
    package: []const u8,
    module: []const u8,
    pass_target: bool,
    pass_optimize: bool,
    backend: ?[]const u8,
    fields: []const []const u8,
};

pub const PackageArtifact = struct {
    package: []const u8,
    artifact: []const u8,
    pass_target: bool,
    pass_optimize: bool,
    backend: ?[]const u8,
};

pub const OptionValue = struct {
    name: []const u8,
    kind: []const u8,
    bool_value: bool,
    string_value: []const u8,
    u32_value: u32,
    commit_value: ?[]const u8,
};

pub const GenArg = struct {
    kind: []const u8,
    value: []const u8,
};

pub const GeneratedImport = struct {
    alias: []const u8,
    tool_root: []const u8,
    tool_name: []const u8,
    args: []const GenArg,
    output: []const u8,
};

pub const GeneratedProducer = enum { tool, command, package };

pub const GeneratedOutput = struct {
    name: []const u8,
    install: ?[]const u8,
};

pub const Generated = struct {
    name: []const u8,
    producer: GeneratedProducer,
    tool_root: ?[]const u8,
    tool_name: ?[]const u8,
    command: []const []const u8,
    package: ?PackageImport,
    package_optimize: std.builtin.OptimizeMode,
    named_path: ?[]const u8,
    args: []const GenArg,
    stdin: ?[]const u8,
    stdout: ?[]const u8,
    outputs: []const GeneratedOutput,
};

pub const GeneratedUseKind = enum { import, embed, c_source, include };

pub const GeneratedUse = struct {
    from: []const u8,
    output: []const u8,
    as: GeneratedUseKind,
    alias: []const u8,
};

pub const Native = struct {
    c_sources: []const []const u8,
    include_dirs: []const []const u8,
    system_include_dirs: []const []const u8,
    library_paths: []const []const u8,
    object_files: []const []const u8,
    system_libs: []const []const u8,
    pkg_config_libs: []const []const u8,
    frameworks: []const []const u8,
    link_libc: bool,
    link_libcpp: bool,
};

pub const Subproject = struct {
    name: []const u8,
    path: []const u8,
    output_dir: []const u8,
    description: []const u8,
};

pub const Module = struct {
    name: []const u8,
    subproject: []const u8,
    artifact_name: []const u8,
    kind: Kind,
    root: []const u8,
    deps: []const []const u8,
    link: Link,
    pre: []const Command,
    post: []const Command,
    install_dirs: []const InstallDir,
    pkg_library_paths: []const PackageLibraryPath,
    pkg_imports: []const PackageImport,
    pkg_artifacts: []const PackageArtifact,
    build_options: []const []const u8,
    option_values: []const OptionValue,
    gen_imports: []const GeneratedImport,
    generated: []const GeneratedUse,
    build_options_import: []const u8,
    native: Native,
    optimize: std.builtin.OptimizeMode,
};

HEADER

echo "$DATA" | python3 -c "
import json, sys

def zig_string(s):
    return json.dumps(s)

def zig_string_list(items):
    if items:
        return '&.{ ' + ', '.join(zig_string(item) for item in items) + ' }'
    return '&.{}'

data = json.load(sys.stdin)
zig = data.get('toolchain', {}).get('zig', {})
lanes = zig.get('lanes', ['0.14', '0.15', '0.16'])
preferred = zig.get('preferred', lanes[0] if lanes else '0.15')

print('pub const toolchain = Toolchain{')
print('    .zig_lanes = ' + zig_string_list(lanes) + ',')
print('    .preferred_zig_lane = ' + zig_string(preferred) + ',')
print('};')
print()
" >> build_spec.zig

echo "$DATA" | python3 -c "
import json, sys

def zig_string(s):
    return json.dumps(s)

def zig_optional_string(s):
    return 'null' if s is None else zig_string(s)

def zig_bool(v):
    return 'true' if v else 'false'

data = json.load(sys.stdin)
packages = data.get('packages', {})
print('pub const packages = [_]Package{')
for name, p in packages.items():
    print('    .{ .name = ' + zig_string(name)
          + ', .url = ' + zig_optional_string(p.get('url'))
          + ', .hash = ' + zig_optional_string(p.get('hash'))
          + ', .path = ' + zig_optional_string(p.get('path'))
          + ', .lazy = ' + zig_bool(p.get('lazy', False))
          + ' },')
print('};')
print()
" >> build_spec.zig

echo "$DATA" | python3 -c "
import json, sys

def zig_string(s):
    return json.dumps(s)

def zig_optional_string(s):
    return 'null' if s is None else zig_string(s)

def zig_optional_bool(v):
    return 'null' if v is None else ('true' if v else 'false')

def zig_optional_u32(v):
    return 'null' if v is None else str(int(v))

data = json.load(sys.stdin)
print('pub const options = [_]Option{')
for item in data.get('options', []):
    typ = item['type']
    default = item.get('default', None)
    bool_default = default if typ == 'bool' and isinstance(default, bool) else None
    string_default = default if typ == 'string' and isinstance(default, str) else None
    u32_default = default if typ == 'u32' and default is not None else None
    print('    .{ .name = ' + zig_string(item['name'])
          + ', .type = .' + typ
          + ', .description = ' + zig_string(item.get('description', ''))
          + ', .bool_default = ' + zig_optional_bool(bool_default)
          + ', .string_default = ' + zig_optional_string(string_default)
          + ', .u32_default = ' + zig_optional_u32(u32_default)
          + ' },')
print('};')
print()
" >> build_spec.zig

echo "$DATA" | python3 -c "
import json, sys

def zig_string(s):
    return json.dumps(s)

def zig_optional_string(s):
    return 'null' if s is None else zig_string(s)

def zig_string_list(items):
    if items:
        return '&.{ ' + ', '.join(zig_string(item) for item in items) + ' }'
    return '&.{}'

data = json.load(sys.stdin)
print('pub const system_deps = [_]SystemDep{')
for item in data.get('system_deps', []):
    print('    .{ .name = ' + zig_string(item['name'])
          + ', .kind = .' + item['kind']
          + ', .os = ' + zig_string_list(item.get('os', []))
          + ', .min_version = ' + zig_optional_string(item.get('min_version'))
          + ', .hint = ' + zig_string(item.get('hint', ''))
          + ' },')
print('};')
print()
" >> build_spec.zig

echo "$DATA" | python3 -c "
import json, sys

def zig_string(s):
    return json.dumps(s)

def zig_optional_string(s):
    return 'null' if s is None else zig_string(s)

def zig_string_list(items):
    if items:
        return '&.{ ' + ', '.join(zig_string(item) for item in items) + ' }'
    return '&.{}'

def zig_bool(v):
    return 'true' if v else 'false'

def fail(message):
    sys.stderr.write('gen_build_spec.sh: ' + message + chr(10))
    sys.exit(1)

data = json.load(sys.stdin)
print('pub const generated = [_]Generated{')
for name, g in data.get('generated', {}).items():
    producers = [k for k in ('tool', 'command', 'package') if g.get(k)]
    if len(producers) != 1:
        fail('generated ' + name + ' must set exactly one of tool, command, package; found ' + (', '.join(producers) or 'none'))
    producer = producers[0]
    outputs = g.get('outputs', [])
    names = [o['name'] for o in outputs]
    if len(set(names)) != len(names):
        fail('generated ' + name + ' declares an output name twice')
    args = g.get('args', [])
    if producer == 'package':
        if args or g.get('stdin') or g.get('stdout'):
            fail('generated ' + name + ' is a package path and takes no args, stdin or stdout')
        if len(outputs) != 1:
            fail('generated ' + name + ' is a package path and must declare exactly one output')
    else:
        produced = [a['value'] for a in args if a['kind'] == 'output_file']
        if g.get('stdout'):
            produced.append(g['stdout'])
        for out in names:
            if out not in produced:
                fail('generated ' + name + ' declares output ' + out + ' but no output_file argument or stdout capture produces it')
        for out in produced:
            if out not in names:
                fail('generated ' + name + ' produces ' + out + ' but does not declare it in outputs')
    tool = g.get('tool') or {}
    pkg = g.get('package')
    if pkg:
        pkg_str = ('.{ .alias = ' + zig_string(name)
                   + ', .package = ' + zig_string(pkg['package'])
                   + ', .module = ' + zig_string('')
                   + ', .pass_target = ' + zig_bool(pkg.get('pass_target', True))
                   + ', .pass_optimize = ' + zig_bool(pkg.get('pass_optimize', True))
                   + ', .backend = ' + zig_optional_string(pkg.get('backend'))
                   + ', .fields = ' + zig_string_list(pkg.get('fields', []))
                   + ' }')
    else:
        pkg_str = 'null'
    if args:
        args_str = '&.{ ' + ', '.join('.{ .kind = ' + zig_string(a['kind']) + ', .value = ' + zig_string(a['value']) + ' }' for a in args) + ' }'
    else:
        args_str = '&.{}'
    outputs_str = '&.{ ' + ', '.join('.{ .name = ' + zig_string(o['name']) + ', .install = ' + zig_optional_string(o.get('install')) + ' }' for o in outputs) + ' }'
    print('    .{')
    print('        .name = ' + zig_string(name) + ',')
    print('        .producer = .' + producer + ',')
    print('        .tool_root = ' + zig_optional_string(tool.get('root')) + ',')
    print('        .tool_name = ' + zig_optional_string(tool.get('name')) + ',')
    print('        .command = ' + zig_string_list(g.get('command', [])) + ',')
    print('        .package = ' + pkg_str + ',')
    print('        .package_optimize = .' + (pkg or {}).get('optimize', 'Debug') + ',')
    print('        .named_path = ' + zig_optional_string((pkg or {}).get('named_path')) + ',')
    print('        .args = ' + args_str + ',')
    print('        .stdin = ' + zig_optional_string(g.get('stdin')) + ',')
    print('        .stdout = ' + zig_optional_string(g.get('stdout')) + ',')
    print('        .outputs = ' + outputs_str + ',')
    print('    },')
print('};')
print()

for mod_name, m in data['modules'].items():
    for use in m.get('generated', []):
        source = data.get('generated', {}).get(use['from'])
        if source is None:
            fail('module ' + mod_name + ' consumes unknown generated step ' + use['from'])
        if use['output'] not in [o['name'] for o in source.get('outputs', [])]:
            fail('module ' + mod_name + ' consumes ' + use['output'] + ', which generated step ' + use['from'] + ' does not declare in outputs')
        if use['as'] in ('import', 'embed') and not use.get('alias'):
            fail('module ' + mod_name + ' consumes ' + use['from'] + '/' + use['output'] + ' as ' + use['as'] + ' and needs an alias')
" >> build_spec.zig

echo "$DATA" | python3 -c "
import json, posixpath, sys

def zig_string(s):
    return json.dumps(s)

def fail(message):
    sys.stderr.write('gen_build_spec.sh: ' + message + chr(10))
    sys.exit(1)

def relative_path(label, value, allow_empty):
    if value == '':
        if allow_empty:
            return
        fail(label + ' must not be empty')
    if value.startswith('/') or value.endswith('/') or posixpath.normpath(value) != value or '..' in value.split('/'):
        fail(label + ' must be a normalized relative path with no .. segments: ' + value)

data = json.load(sys.stdin)
subs = data.get('subprojects', {})
paths = {}
print('pub const subprojects = [_]Subproject{')
for name, sub in subs.items():
    label = 'subproject ' + name
    relative_path(label + ' path', sub['path'], False)
    relative_path(label + ' output_dir', sub.get('output_dir', ''), True)
    if sub['path'] in paths:
        fail(label + ' has the same path as subproject ' + paths[sub['path']] + ': ' + sub['path'])
    paths[sub['path']] = name
    print('    .{ .name = ' + zig_string(name)
          + ', .path = ' + zig_string(sub['path'])
          + ', .output_dir = ' + zig_string(sub.get('output_dir', ''))
          + ', .description = ' + zig_string(sub.get('description', ''))
          + ' },')
print('};')
print()

for mod_name, m in data['modules'].items():
    owner = m.get('subproject', '')
    if not owner:
        continue
    if owner not in subs:
        fail('module ' + mod_name + ' belongs to unknown subproject ' + owner)
    base = subs[owner]['path']
    if not m['root'].startswith(base + '/'):
        fail('module ' + mod_name + ' root ' + m['root'] + ' is outside subproject ' + owner + ' (' + base + ')')
" >> build_spec.zig

printf 'pub const modules = [_]Module{\n' >> build_spec.zig

echo "$DATA" | python3 -c "
import json, sys

def zig_string(s):
    return json.dumps(s)

def zig_optional_string(s):
    return 'null' if s is None else zig_string(s)

def zig_string_list(items):
    if items:
        return '&.{ ' + ', '.join(zig_string(item) for item in items) + ' }'
    return '&.{}'

def zig_commands(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        rendered.append('.{ .argv = ' + zig_string_list(item.get('argv', [])) + ' }')
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_install_dirs(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        rendered.append(
            '.{ .source_dir = ' + zig_string(item['source_dir'])
            + ', .install_dir = ' + zig_string(item.get('install_dir', 'bin'))
            + ', .install_subdir = ' + zig_string(item['install_subdir'])
            + ' }'
        )
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_pkg_library_paths(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        rendered.append(
            '.{ .package = ' + zig_string(item['package'])
            + ', .path = ' + zig_string(item.get('path', ''))
            + ', .os = ' + zig_optional_string(item.get('os'))
            + ', .arch = ' + zig_optional_string(item.get('arch'))
            + ' }'
        )
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_pkg_imports(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        rendered.append(
            '.{ .alias = ' + zig_string(item['alias'])
            + ', .package = ' + zig_string(item['package'])
            + ', .module = ' + zig_string(item['module'])
            + ', .pass_target = ' + zig_bool(item.get('pass_target', True))
            + ', .pass_optimize = ' + zig_bool(item.get('pass_optimize', True))
            + ', .backend = ' + zig_optional_string(item.get('backend'))
            + ', .fields = ' + zig_string_list(item.get('fields', []))
            + ' }'
        )
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_pkg_artifacts(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        rendered.append(
            '.{ .package = ' + zig_string(item['package'])
            + ', .artifact = ' + zig_string(item['artifact'])
            + ', .pass_target = ' + zig_bool(item.get('pass_target', True))
            + ', .pass_optimize = ' + zig_bool(item.get('pass_optimize', True))
            + ', .backend = ' + zig_optional_string(item.get('backend'))
            + ' }'
        )
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_bool(v):
    return 'true' if v else 'false'

def zig_option_values(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        kind = item['kind']
        commit = item.get('commit')
        commit_field = 'null' if (kind != 'opt_commit' or not commit) else zig_string(commit)
        rendered.append(
            '.{ .name = ' + zig_string(item['name'])
            + ', .kind = ' + zig_string(kind)
            + ', .bool_value = ' + zig_bool(item.get('bool_value', False))
            + ', .string_value = ' + zig_string(item.get('string_value', ''))
            + ', .u32_value = ' + str(int(item.get('u32_value', 0)))
            + ', .commit_value = ' + commit_field
            + ' }'
        )
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_gen_imports(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        args = item.get('args', [])
        if args:
            arg_parts = ['.{ .kind = ' + zig_string(a['kind']) + ', .value = ' + zig_string(a['value']) + ' }' for a in args]
            args_str = '&.{ ' + ', '.join(arg_parts) + ' }'
        else:
            args_str = '&.{}'
        rendered.append(
            '.{ .alias = ' + zig_string(item['alias'])
            + ', .tool_root = ' + zig_string(item['tool_root'])
            + ', .tool_name = ' + zig_string(item['tool_name'])
            + ', .args = ' + args_str
            + ', .output = ' + zig_string(item['output'])
            + ' }'
        )
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_generated_uses(items):
    if not items:
        return '&.{}'
    rendered = []
    for item in items:
        rendered.append(
            '.{ .from = ' + zig_string(item['from'])
            + ', .output = ' + zig_string(item['output'])
            + ', .as = .' + item['as']
            + ', .alias = ' + zig_string(item.get('alias', ''))
            + ' }'
        )
    return '&.{ ' + ', '.join(rendered) + ' }'

def zig_native(item):
    item = item or {}
    return '''.{{
            .c_sources = {c_sources},
            .include_dirs = {include_dirs},
            .system_include_dirs = {system_include_dirs},
            .library_paths = {library_paths},
            .object_files = {object_files},
            .system_libs = {system_libs},
            .pkg_config_libs = {pkg_config_libs},
            .frameworks = {frameworks},
            .link_libc = {link_libc},
            .link_libcpp = {link_libcpp},
        }}'''.format(
        c_sources=zig_string_list(item.get('c_sources', [])),
        include_dirs=zig_string_list(item.get('include_dirs', [])),
        system_include_dirs=zig_string_list(item.get('system_include_dirs', [])),
        library_paths=zig_string_list(item.get('library_paths', [])),
        object_files=zig_string_list(item.get('object_files', [])),
        system_libs=zig_string_list(item.get('system_libs', [])),
        pkg_config_libs=zig_string_list(item.get('pkg_config_libs', [])),
        frameworks=zig_string_list(item.get('frameworks', [])),
        link_libc=zig_bool(item.get('link_libc', False)),
        link_libcpp=zig_bool(item.get('link_libcpp', False)),
    )

data = json.load(sys.stdin)
mods = data['modules']

for name, m in mods.items():
    kind = '.' + m['kind']
    link = '.' + m.get('link', 'abi')
    opt_map = {'Debug': '.Debug', 'ReleaseFast': '.ReleaseFast', 'ReleaseSafe': '.ReleaseSafe', 'ReleaseSmall': '.ReleaseSmall'}
    opt = opt_map[m['optimize']]
    deps = m.get('deps', [])
    deps_str = zig_string_list(deps)
    pre_str = zig_commands(m.get('pre', []))
    post_str = zig_commands(m.get('post', []))
    install_dirs_str = zig_install_dirs(m.get('install_dirs', []))
    pkg_library_paths_str = zig_pkg_library_paths(m.get('pkg_library_paths', []))
    pkg_imports_str = zig_pkg_imports(m.get('pkg_imports', []))
    pkg_artifacts_str = zig_pkg_artifacts(m.get('pkg_artifacts', []))
    build_options_str = zig_string_list(m.get('build_options', []))
    option_values_str = zig_option_values(m.get('option_values', []))
    gen_imports_str = zig_gen_imports(m.get('gen_imports', []))
    generated_str = zig_generated_uses(m.get('generated', []))
    native_str = zig_native(m.get('native', {}))
    print(f'''    .{{
        .name = {zig_string(name)},
        .subproject = {zig_string(m.get('subproject', ''))},
        .artifact_name = {zig_string(m.get('artifact_name', name))},
        .kind = {kind},
        .root = {zig_string(m['root'])},
        .deps = {deps_str},
        .link = {link},
        .pre = {pre_str},
        .post = {post_str},
        .install_dirs = {install_dirs_str},
        .pkg_library_paths = {pkg_library_paths_str},
        .pkg_imports = {pkg_imports_str},
        .pkg_artifacts = {pkg_artifacts_str},
        .build_options = {build_options_str},
        .option_values = {option_values_str},
        .gen_imports = {gen_imports_str},
        .generated = {generated_str},
        .build_options_import = {zig_string(m.get('build_options_import', 'build-options'))},
        .native = {native_str},
        .optimize = {opt},
    }},''')
" >> build_spec.zig

printf '};\n' >> build_spec.zig

echo "Generated build_spec.zig"

# Record the input signature so the next run can skip regeneration.
printf "%s" "$SIG" > "$STAMP"
