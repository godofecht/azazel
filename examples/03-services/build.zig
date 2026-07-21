// The same module-graph walk the repo root uses.
//
// Pass 1 creates one Compile step per module in build_spec.zig.
// Pass 2 resolves `deps` by name and links them.
//
// The only example-specific part is the list of test suites at the bottom.
const std = @import("std");
const spec = @import("build_spec.zig");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});

    var built = std.StringHashMap(*std.Build.Step.Compile).init(b.allocator);
    defer built.deinit();

    for (spec.modules) |m| {
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

        // Without this an installed executable can only find an installed
        // shared library when the build cache happens to sit in the current
        // directory. Point the loader at ../lib relative to the binary.
        if (m.kind == .exe) {
            step.root_module.addRPathSpecial(switch (target.result.os.tag) {
                .macos, .ios, .tvos, .watchos => "@loader_path/../lib",
                else => "$ORIGIN/../lib",
            });
        }

        b.installArtifact(step);
    }

    // --- tests ---
    //
    // Two suites: the build-spec invariants build() relies on above, and the
    // protocol/codec round-trip.
    const test_step = b.step("test", "Run all tests");

    const suites = [_][]const u8{
        "spec_test.zig",
        "src/codec_test.zig",
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
        // spec_test.zig checks module roots on disk, so run from this directory.
        run_t.setCwd(b.path("."));
        test_step.dependOn(&run_t.step);
    }
}
