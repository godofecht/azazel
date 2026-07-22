const std = @import("std");
const spec = @import("build_spec.zig");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});

    var built = std.StringHashMap(*std.Build.Step.Compile).init(b.allocator);
    defer built.deinit();

    for (spec.modules) |m| {
        // Zig 0.15 takes target and optimize on the module rather than on the
        // compile step, and folds addStaticLibrary/addSharedLibrary into
        // addLibrary with an explicit linkage.
        const mod = b.createModule(.{
            .root_source_file = b.path(m.root),
            .target = target,
            .optimize = m.optimize,
        });

        const step = switch (m.kind) {
            .exe => b.addExecutable(.{
                .name = m.name,
                .root_module = mod,
            }),
            .static => b.addLibrary(.{
                .name = m.name,
                .root_module = mod,
                .linkage = .static,
            }),
            .shared => b.addLibrary(.{
                .name = m.name,
                .root_module = mod,
                .linkage = .dynamic,
            }),
        };

        built.put(m.name, step) catch unreachable;
    }

    for (spec.modules) |m| {
        const step = built.get(m.name).?;
        for (m.deps) |dep| {
            // 0.16 moved linkLibrary from Compile onto Module. Module.linkLibrary
            // exists in 0.14 and 0.15 too, so this spelling works on all three.
            step.root_module.linkLibrary(built.get(dep).?);
        }
        if (m.kind == .exe or m.kind == .shared or m.kind == .static) {
            b.installArtifact(step);
        }
    }

    // --- tests ---
    //
    // Three suites: the build-spec invariants that build.zig above relies on,
    // the small src/ helpers, and the vendored danzig core.
    const test_step = b.step("test", "Run all tests");

    const suites = [_][]const u8{
        "build_spec_test.zig",
        "src/core_test.zig",
        "src/danzig/tests.zig",
    };

    for (suites) |suite| {
        const t = b.addTest(.{
            .root_module = b.createModule(.{
                .root_source_file = b.path(suite),
                .target = target,
                .optimize = .Debug,
            }),
        });
        const run_t = b.addRunArtifact(t);
        // build_spec_test reads module roots off disk, so run from the repo root.
        run_t.setCwd(b.path("."));
        test_step.dependOn(&run_t.step);
    }
}
