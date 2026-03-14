const std = @import("std");
const spec = @import("build_spec.zig");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});

    var built = std.StringHashMap(*std.Build.Step.Compile).init(b.allocator);
    defer built.deinit();

    for (spec.modules) |m| {
        const step = switch (m.kind) {
            .exe => b.addExecutable(.{
                .name = m.name,
                .root_source_file = b.path(m.root),
                .optimize = m.optimize,
                .target = target,
            }),
            .static => b.addStaticLibrary(.{
                .name = m.name,
                .root_source_file = b.path(m.root),
                .optimize = m.optimize,
                .target = target,
            }),
            .shared => b.addSharedLibrary(.{
                .name = m.name,
                .root_source_file = b.path(m.root),
                .optimize = m.optimize,
                .target = target,
            }),
        };

        built.put(m.name, step) catch unreachable;
    }

    for (spec.modules) |m| {
        const step = built.get(m.name).?;
        for (m.deps) |dep| {
            step.linkLibrary(built.get(dep).?);
        }
        if (m.kind == .exe) b.installArtifact(step);
    }
}
