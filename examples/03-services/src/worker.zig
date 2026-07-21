// Links `protocol` only, and is built with the default debug profile.

const std = @import("std");
const builtin = @import("builtin");

extern fn protocol_magic() u32;
extern fn protocol_checksum(bytes: [*]const u8, len: usize) u32;

pub fn main() void {
    const job = "resize:1920x1080";

    std.debug.print("worker ({s})\n", .{@tagName(builtin.mode)});
    std.debug.print("  magic    = 0x{X}\n", .{protocol_magic()});
    std.debug.print("  job      = {s}\n", .{job});
    std.debug.print("  checksum = {d}\n", .{protocol_checksum(job, job.len)});
}
