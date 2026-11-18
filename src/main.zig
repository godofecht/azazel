const std = @import("std");
const build_info = @import("build_info");

pub fn main() void {
    std.debug.print("azazel {s}\n", .{build_info.version});
}
