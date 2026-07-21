// Invariants build.zig relies on when it walks build_spec.zig.

const std = @import("std");
const testing = std.testing;
const spec = @import("build_spec.zig");

fn find(name: []const u8) ?spec.Module {
    for (spec.modules) |m| {
        if (std.mem.eql(u8, m.name, name)) return m;
    }
    return null;
}

test "all four modules are present" {
    try testing.expectEqual(@as(usize, 4), spec.modules.len);
    for ([_][]const u8{ "protocol", "codec", "gateway", "worker" }) |name| {
        try testing.expect(find(name) != null);
    }
}

test "every module root exists on disk" {
    var dir = try std.fs.cwd().openDir(".", .{});
    defer dir.close();

    for (spec.modules) |m| {
        dir.access(m.root, .{}) catch |err| {
            std.debug.print("missing root for module '{s}': {s}\n", .{ m.name, m.root });
            return err;
        };
    }
}

test "kinds match the intent of project.cue" {
    try testing.expectEqual(spec.Kind.static, find("protocol").?.kind);
    try testing.expectEqual(spec.Kind.shared, find("codec").?.kind);
    try testing.expectEqual(spec.Kind.exe, find("gateway").?.kind);
    try testing.expectEqual(spec.Kind.exe, find("worker").?.kind);
}

test "worker keeps the default debug profile, everything else is release" {
    try testing.expectEqual(std.builtin.OptimizeMode.Debug, find("worker").?.optimize);
    try testing.expectEqual(std.builtin.OptimizeMode.ReleaseFast, find("protocol").?.optimize);
    try testing.expectEqual(std.builtin.OptimizeMode.ReleaseFast, find("codec").?.optimize);
    try testing.expectEqual(std.builtin.OptimizeMode.ReleaseFast, find("gateway").?.optimize);
}

test "protocol is depended on by codec, gateway and worker" {
    var dependents: usize = 0;
    for (spec.modules) |m| {
        for (m.deps) |dep| {
            if (std.mem.eql(u8, dep, "protocol")) dependents += 1;
        }
    }
    try testing.expectEqual(@as(usize, 3), dependents);
}

test "every declared dependency resolves to a declared module" {
    for (spec.modules) |m| {
        for (m.deps) |dep| {
            if (find(dep) == null) {
                std.debug.print("module '{s}' depends on undeclared '{s}'\n", .{ m.name, dep });
                return error.UnresolvedDependency;
            }
        }
    }
}

test "the dependency graph is acyclic" {
    // Kahn's algorithm. build.zig links in spec order, so a cycle is
    // unbuildable.
    var remaining: [spec.modules.len]bool = .{true} ** spec.modules.len;
    var resolved: usize = 0;

    var progress = true;
    while (progress) {
        progress = false;
        for (spec.modules, 0..) |m, i| {
            if (!remaining[i]) continue;

            var deps_met = true;
            for (m.deps) |dep| {
                for (spec.modules, 0..) |other, j| {
                    if (std.mem.eql(u8, other.name, dep) and remaining[j]) deps_met = false;
                }
            }

            if (deps_met) {
                remaining[i] = false;
                resolved += 1;
                progress = true;
            }
        }
    }

    try testing.expectEqual(spec.modules.len, resolved);
}
