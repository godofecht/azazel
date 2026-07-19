// Tests for the small pure helpers exposed by the top-level src/ modules.
//
// These are scaffolding modules used to exercise the CUE build pipeline, so
// the coverage here is deliberately thin: it pins the declared behaviour and
// nothing more.

const std = @import("std");
const testing = std.testing;

const core = @import("core.zig");
const math = @import("math.zig");
const utils = @import("utils.zig");
const protocol = @import("protocol.zig");

test "core.add" {
    try testing.expectEqual(@as(i32, 5), core.add(2, 3));
    try testing.expectEqual(@as(i32, 0), core.add(-3, 3));
    try testing.expectEqual(@as(i32, -5), core.add(-2, -3));
}

test "math.multiply" {
    try testing.expectEqual(@as(i32, 6), math.multiply(2, 3));
    try testing.expectEqual(@as(i32, 0), math.multiply(0, 99));
    try testing.expectEqual(@as(i32, -6), math.multiply(-2, 3));
}

test "utils.clamp: below, inside, above" {
    try testing.expectEqual(@as(i32, 0), utils.clamp(-5, 0, 10));
    try testing.expectEqual(@as(i32, 5), utils.clamp(5, 0, 10));
    try testing.expectEqual(@as(i32, 10), utils.clamp(15, 0, 10));
}

test "utils.clamp: boundaries are inclusive" {
    try testing.expectEqual(@as(i32, 0), utils.clamp(0, 0, 10));
    try testing.expectEqual(@as(i32, 10), utils.clamp(10, 0, 10));
}

test "protocol.MAGIC is stable" {
    // Wire constant — changing it breaks compatibility with existing peers.
    try testing.expectEqual(@as(u32, 0xA2A2), protocol.MAGIC);
}

test "protocol.encode: empty input hashes to zero" {
    try testing.expectEqual(@as(u32, 0), protocol.encode(""));
}

test "protocol.encode is deterministic" {
    try testing.expectEqual(protocol.encode("azazel"), protocol.encode("azazel"));
}

test "protocol.encode distinguishes different inputs" {
    try testing.expect(protocol.encode("a") != protocol.encode("b"));
    try testing.expect(protocol.encode("ab") != protocol.encode("ba"));
}

test "protocol.encode wraps rather than overflowing" {
    // The hash uses wrapping arithmetic; a long input must not trap.
    const long = "x" ** 4096;
    _ = protocol.encode(long);
}
