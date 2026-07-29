const std = @import("std");

extern fn geometry_total(r: f64, side: f64) f64;
extern fn stats_variance(xs: [*]const f64, len: usize) f64;

pub fn main() void {
    const data = [_]f64{ 2, 4, 4, 4, 5, 5, 7, 9 };
    std.debug.print("geometry_total(1, 2) = {d:.4}\n", .{geometry_total(1, 2)});
    std.debug.print("stats_variance     = {d:.4}\n", .{stats_variance(&data, data.len)});
}
