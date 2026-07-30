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

    // A Zig module for every declared module, and a compile step only for the
    // ones that become a real artifact. An `import` dependency is merged into
    // its dependents as a module, so it needs no artifact and no link step.
    var modules = std.StringHashMap(*std.Build.Module).init(b.allocator);
    var steps = std.StringHashMap(*std.Build.Step.Compile).init(b.allocator);
    defer modules.deinit();
    defer steps.deinit();

    for (spec.modules) |m| {
        // Zig 0.15 takes target and optimize on the module rather than on the
        // compile step, and folds addStaticLibrary/addSharedLibrary into
        // addLibrary with an explicit linkage.
        const mod = b.createModule(.{
            .root_source_file = b.path(m.root),
            .target = target,
            .optimize = m.optimize,
        });
        modules.put(m.name, mod) catch unreachable;
    }

    for (spec.modules) |m| {
        // Executables and shared libraries are always artifacts. A static
        // library is an artifact only when it is linked over the ABI; an
        // `import` static module compiles inside its dependents.
        const needs_artifact = switch (m.kind) {
            .exe, .shared => true,
            .static => m.link == .abi,
        };
        if (!needs_artifact) continue;

        const mod = modules.get(m.name).?;
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
        steps.put(m.name, step) catch unreachable;
    }

    for (spec.modules) |m| {
        const mod = modules.get(m.name).?;
        for (m.deps) |dep| {
            if (linkOf(dep) == .import and kindOf(dep) == .static) {
                // Merge the dependency into this compilation. Its source is
                // reached with `@import("<name>")`.
                mod.addImport(dep, modules.get(dep).?);
            } else {
                // 0.16 moved linkLibrary from Compile onto Module. Module.linkLibrary
                // exists in 0.14 and 0.15 too, so this spelling works on all three.
                mod.linkLibrary(steps.get(dep).?);
            }
        }
    }

    for (spec.modules) |m| {
        if (steps.get(m.name)) |step| b.installArtifact(step);
    }

    // --- tests ---
    //
    // Three suites: the build-spec invariants that build.zig above relies on,
    // the small src/ helpers, and the vendored danzig core.
    const test_step = b.step("test", "Run all tests");

    const suites = [_][]const u8{
        "compat.zig",
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
