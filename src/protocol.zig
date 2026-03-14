pub const MAGIC: u32 = 0xA2A2;

pub fn encode(data: []const u8) u32 {
    var hash: u32 = 0;
    for (data) |byte| {
        hash = hash *% 31 +% byte;
    }
    return hash;
}
