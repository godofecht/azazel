// A shared library that itself depends on `protocol`.
//
// Frames are `[magic:u32][checksum:u32][payload]`, little-endian.

const std = @import("std");

extern fn protocol_magic() u32;
extern fn protocol_checksum(bytes: [*]const u8, len: usize) u32;

pub const HEADER_LEN: usize = 8;

/// Writes a frame into `out`. Returns the number of bytes written, or 0 if
/// `out` is too small.
pub export fn codec_encode(
    payload: [*]const u8,
    payload_len: usize,
    out: [*]u8,
    out_len: usize,
) usize {
    const total = HEADER_LEN + payload_len;
    if (out_len < total) return 0;

    std.mem.writeInt(u32, out[0..4], protocol_magic(), .little);
    std.mem.writeInt(u32, out[4..8], protocol_checksum(payload, payload_len), .little);
    @memcpy(out[HEADER_LEN..total], payload[0..payload_len]);
    return total;
}

/// Returns true if `frame` carries the right magic and a matching checksum.
pub export fn codec_verify(frame: [*]const u8, frame_len: usize) bool {
    if (frame_len < HEADER_LEN) return false;

    const magic = std.mem.readInt(u32, frame[0..4], .little);
    if (magic != protocol_magic()) return false;

    const want = std.mem.readInt(u32, frame[4..8], .little);
    const payload = frame + HEADER_LEN;
    return want == protocol_checksum(payload, frame_len - HEADER_LEN);
}
