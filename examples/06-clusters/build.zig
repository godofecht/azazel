// The same module-graph walk the repo root uses, with `link` modes.
//
// Pass 1 creates a Zig module for every module in build_spec.zig.
// Pass 2 creates a compile step only for real artifacts (exe, shared, and any
//        static marked link: "abi"). An `import` module has no artifact.
// Pass 3 wires deps: an `import` dep joins the graph with addImport (one
//        compilation), an `abi` dep links as a library.
//
// Nothing here is example-specific. Copy this directory to start a project.
const std = @import("std");
const spec = @import("build_spec.zig");

fn linkOf(name: []const u8) spec.Link {
    for (spec.modules) |m| {
        if (std.mem.eql(u8, m.name, name)) return m.link;
    }
    return .abi;
}

fn kindOf(name: []const u8) spec.Kind {
    for (spec.modules) |m| {
        if (std.mem.eql(u8, m.name, name)) return m.kind;
    }
    return .static;
}

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});

    var modules = std.StringHashMap(*std.Build.Module).init(b.allocator);
    var steps = std.StringHashMap(*std.Build.Step.Compile).init(b.allocator);
    defer modules.deinit();
    defer steps.deinit();

    for (spec.modules) |m| {
        const mod = b.createModule(.{
            .root_source_file = b.path(m.root),
            .target = target,
            .optimize = m.optimize,
        });
        modules.put(m.name, mod) catch unreachable;
    }

    for (spec.modules) |m| {
        const needs_artifact = switch (m.kind) {
            .exe, .shared => true,
            .static => m.link == .abi,
        };
        if (!needs_artifact) continue;

        const mod = modules.get(m.name).?;
        const step = switch (m.kind) {
            .exe => b.addExecutable(.{ .name = m.name, .root_module = mod }),
            .static => b.addLibrary(.{ .name = m.name, .root_module = mod, .linkage = .static }),
            .shared => b.addLibrary(.{ .name = m.name, .root_module = mod, .linkage = .dynamic }),
        };
        steps.put(m.name, step) catch unreachable;
    }

    for (spec.modules) |m| {
        const mod = modules.get(m.name).?;
        for (m.deps) |dep| {
            if (linkOf(dep) == .import and kindOf(dep) == .static) {
                mod.addImport(dep, modules.get(dep).?);
            } else {
                mod.linkLibrary(steps.get(dep).?);
            }
        }

        // Point an installed executable at ../lib so it can find an installed
        // shared library. Harmless when there is no shared dependency.
        if (m.kind == .exe) {
            mod.addRPathSpecial(switch (target.result.os.tag) {
                .macos, .ios, .tvos, .watchos => "@loader_path/../lib",
                else => "$ORIGIN/../lib",
            });
        }
    }

    for (spec.modules) |m| {
        if (steps.get(m.name)) |step| b.installArtifact(step);
    }
}
