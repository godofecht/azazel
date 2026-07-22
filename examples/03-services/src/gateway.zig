// Links both `protocol` (static) and `codec` (shared).

const std = @import("std");
const builtin = @import("builtin");

extern fn protocol_magic() u32;
extern fn codec_encode(payload: [*]const u8, payload_len: usize, out: [*]u8, out_len: usize) usize;
extern fn codec_verify(frame: [*]const u8, frame_len: usize) bool;

pub fn main() void {
    const payload = "ping";
    var frame: [64]u8 = undefined;

    const n = codec_encode(payload, payload.len, &frame, frame.len);

    std.debug.print("gateway ({s})\n", .{@tagName(builtin.mode)});
    std.debug.print("  magic       = 0x{X}\n", .{protocol_magic()});
    std.debug.print("  frame bytes = {d}\n", .{n});
    std.debug.print("  verify      = {}\n", .{codec_verify(&frame, n)});

    // Corrupt the payload and the checksum stops matching.
    frame[8] = 'P';
    std.debug.print("  tampered    = {}\n", .{codec_verify(&frame, n)});
}
