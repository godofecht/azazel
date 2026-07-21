const std = @import("std");
const builtin = @import("builtin");

// Declared, never defined here. The linker resolves these against libmathlib.a
// because project.cue lists `mathlib` in calc's deps.
extern fn mathlib_add(a: i32, b: i32) i32;
extern fn mathlib_mul(a: i32, b: i32) i32;
extern fn mathlib_clamp(v: i32, lo: i32, hi: i32) i32;

pub fn main() void {
    std.debug.print("calc built as {s}\n", .{@tagName(builtin.mode)});
    std.debug.print("  add(2, 3)         = {d}\n", .{mathlib_add(2, 3)});
    std.debug.print("  mul(6, 7)         = {d}\n", .{mathlib_mul(6, 7)});
    std.debug.print("  clamp(15, 0, 10)  = {d}\n", .{mathlib_clamp(15, 0, 10)});
}
