// Wire format shared by every module in this example.
//
// Everything crossing a module boundary is an exported C-ABI symbol, because
// azazel's `deps` is a link edge and not a Zig import.

pub const MAGIC: u32 = 0xA2A2;

pub export fn protocol_magic() u32 {
    return MAGIC;
}

/// FNV-style rolling hash. Wrapping arithmetic, so it never traps.
pub export fn protocol_checksum(bytes: [*]const u8, len: usize) u32 {
    var hash: u32 = 0;
    for (bytes[0..len]) |b| {
        hash = hash *% 31 +% b;
    }
    return hash;
}
