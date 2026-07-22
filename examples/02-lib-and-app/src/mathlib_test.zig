const std = @import("std");
const testing = std.testing;
const mathlib = @import("mathlib.zig");

test "mathlib_add" {
    try testing.expectEqual(@as(i32, 5), mathlib.mathlib_add(2, 3));
    try testing.expectEqual(@as(i32, 0), mathlib.mathlib_add(-3, 3));
}

test "mathlib_mul wraps rather than trapping" {
    try testing.expectEqual(@as(i32, 42), mathlib.mathlib_mul(6, 7));
    _ = mathlib.mathlib_mul(std.math.maxInt(i32), 2);
}

test "mathlib_clamp: below, inside, above" {
    try testing.expectEqual(@as(i32, 0), mathlib.mathlib_clamp(-5, 0, 10));
    try testing.expectEqual(@as(i32, 5), mathlib.mathlib_clamp(5, 0, 10));
    try testing.expectEqual(@as(i32, 10), mathlib.mathlib_clamp(15, 0, 10));
}
