// Unit tests for the protocol/codec pair.
//
// The test binary is a single compilation, so `protocol.zig` is imported here
// to make its exported symbols available to `codec.zig`'s `extern`
// declarations. In the real build those symbols come from libprotocol.a.

const std = @import("std");
const testing = std.testing;

const protocol = @import("protocol.zig");
const codec = @import("codec.zig");

comptime {
    // Force protocol's exports to be emitted into the test binary.
    _ = protocol;
}

test "protocol.MAGIC is stable" {
    // Wire constant. Changing it breaks compatibility with existing peers.
    try testing.expectEqual(@as(u32, 0xA2A2), protocol.MAGIC);
    try testing.expectEqual(protocol.MAGIC, protocol.protocol_magic());
}

test "checksum of an empty payload is zero" {
    const empty = "";
    try testing.expectEqual(@as(u32, 0), protocol.protocol_checksum(empty, 0));
}

test "checksum distinguishes order" {
    const ab = "ab";
    const ba = "ba";
    try testing.expect(protocol.protocol_checksum(ab, 2) != protocol.protocol_checksum(ba, 2));
}

test "encode then verify round-trips" {
    const payload = "ping";
    var frame: [64]u8 = undefined;

    const n = codec.codec_encode(payload, payload.len, &frame, frame.len);
    try testing.expectEqual(codec.HEADER_LEN + payload.len, n);
    try testing.expect(codec.codec_verify(&frame, n));
}

test "encode refuses a buffer that is too small" {
    const payload = "ping";
    var frame: [4]u8 = undefined;
    try testing.expectEqual(@as(usize, 0), codec.codec_encode(payload, payload.len, &frame, frame.len));
}

test "verify rejects a tampered payload" {
    const payload = "ping";
    var frame: [64]u8 = undefined;

    const n = codec.codec_encode(payload, payload.len, &frame, frame.len);
    frame[codec.HEADER_LEN] = 'P';
    try testing.expect(!codec.codec_verify(&frame, n));
}

test "verify rejects a short frame" {
    var frame: [4]u8 = .{ 0, 0, 0, 0 };
    try testing.expect(!codec.codec_verify(&frame, frame.len));
}
