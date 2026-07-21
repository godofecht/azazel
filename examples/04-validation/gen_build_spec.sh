#!/bin/sh
# Generate build_spec.zig from CUE definitions.
# No JSON runtime — CUE exports directly to Zig source.
set -e

cd "$(dirname "$0")"

DATA=$(cue export -e build)

cat > build_spec.zig <<'HEADER'
const std = @import("std");

pub const Kind = enum { exe, static, shared };

pub const Module = struct {
    name: []const u8,
    kind: Kind,
    root: []const u8,
    deps: []const []const u8,
    optimize: std.builtin.OptimizeMode,
};

HEADER

printf 'pub const modules = [_]Module{\n' >> build_spec.zig

echo "$DATA" | python3 -c "
import json, sys

data = json.load(sys.stdin)
mods = data['modules']

for name, m in mods.items():
    kind = '.' + m['kind']
    opt_map = {'Debug': '.Debug', 'ReleaseFast': '.ReleaseFast', 'ReleaseSafe': '.ReleaseSafe', 'ReleaseSmall': '.ReleaseSmall'}
    opt = opt_map[m['optimize']]
    deps = m.get('deps', [])
    if deps:
        deps_str = '&.{ ' + ', '.join('\"' + d + '\"' for d in deps) + ' }'
    else:
        deps_str = '&.{}'
    print(f'''    .{{
        .name = \"{name}\",
        .kind = {kind},
        .root = \"{m['root']}\",
        .deps = {deps_str},
        .optimize = {opt},
    }},''')
" >> build_spec.zig

printf '};\n' >> build_spec.zig

echo "Generated build_spec.zig"
