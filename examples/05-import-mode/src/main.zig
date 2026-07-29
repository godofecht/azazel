const std = @import("std");
const mathlib = @import("mathlib");

pub fn main() void {
    const sum = mathlib.add(2, 3);
    const product = mathlib.mul(4, 5);
    std.debug.print("add(2, 3) = {d}\n", .{sum});
    std.debug.print("mul(4, 5) = {d}\n", .{product});
}
