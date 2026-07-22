// Invariants build.zig relies on when it walks build_spec.zig.
//
// These catch a bad project.cue at `zig build test` time with a readable
// message, rather than as a panic inside build.zig or a linker error.

const std = @import("std");
const testing = std.testing;
const spec = @import("build_spec.zig");

fn hasModule(name: []const u8) bool {
    for (spec.modules) |m| {
        if (std.mem.eql(u8, m.name, name)) return true;
    }
    return false;
}

test "module names are unique" {
    for (spec.modules, 0..) |a, i| {
        for (spec.modules[i + 1 ..]) |b| {
            try testing.expect(!std.mem.eql(u8, a.name, b.name));
        }
    }
}

test "every declared dependency resolves to a declared module" {
    // build.zig does `built.get(dep).?`. An unresolved dep panics there.
    for (spec.modules) |m| {
        for (m.deps) |dep| {
            if (!hasModule(dep)) {
                std.debug.print("module '{s}' depends on undeclared '{s}'\n", .{ m.name, dep });
                return error.UnresolvedDependency;
            }
        }
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

test "calc is the executable and is built for release" {
    for (spec.modules) |m| {
        if (std.mem.eql(u8, m.name, "calc")) {
            try testing.expectEqual(spec.Kind.exe, m.kind);
            try testing.expectEqual(std.builtin.OptimizeMode.ReleaseFast, m.optimize);
        }
    }
}

test "mathlib takes the default debug profile" {
    for (spec.modules) |m| {
        if (std.mem.eql(u8, m.name, "mathlib")) {
            try testing.expectEqual(spec.Kind.static, m.kind);
            try testing.expectEqual(std.builtin.OptimizeMode.Debug, m.optimize);
        }
    }
}
