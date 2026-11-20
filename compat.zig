//! Zig 0.14 / 0.15 / 0.16 filesystem divergences in one place, matching the
//! adaptor zaza uses. Zig 0.16 moved the filesystem under `std.Io` and threads
//! an `Io` handle through every call. Each helper takes an `io` that is a real
//! `Io` on 0.16 and an ignored `void` on the older versions; only the branch
//! for the running compiler is analysed.

const std = @import("std");

/// True only on Zig 0.16, where filesystem calls take an `Io`.
pub const has_io = !@hasDecl(std.fs, "cwd");

/// A process-wide `Io` for standalone programs. On 0.14 and 0.15 this is a
/// `void` the helpers ignore.
pub fn io() if (has_io) std.Io else void {
    if (comptime has_io) return std.Io.Threaded.global_single_threaded.io();
    return {};
}

/// Whether a path exists and is accessible, relative to the current directory.
pub fn exists(ioh: anytype, path: []const u8) bool {
    if (comptime has_io) {
        std.Io.Dir.cwd().access(ioh, path, .{}) catch return false;
    } else {
        std.fs.cwd().access(path, .{}) catch return false;
    }
    return true;
}

/// Read a whole file relative to the current directory, or null on error.
pub fn readFile(ioh: anytype, alloc: std.mem.Allocator, path: []const u8) ?[]u8 {
    if (comptime has_io) {
        return std.Io.Dir.cwd().readFileAlloc(ioh, path, alloc, .unlimited) catch null;
    } else {
        return std.fs.cwd().readFileAlloc(alloc, path, 64 * 1024 * 1024) catch null;
    }
}

test "exists through the adaptor" {
    const ioh = io();
    try std.testing.expect(exists(ioh, "schema.cue"));
    try std.testing.expect(!exists(ioh, "definitely-not-a-real-file.xyz"));
}

/// Glob matching for target paths, shared with `tools/workspace.py`.
///
/// `*` matches any run of characters except `/`. `?` matches one character
/// except `/`. `**` matches any run of characters including `/`, and `**/`
/// also matches zero path segments. Every other character matches itself.
pub fn globMatch(pattern: []const u8, text: []const u8) bool {
    if (pattern.len == 0) return text.len == 0;
    if (pattern[0] == '*') {
        if (pattern.len >= 2 and pattern[1] == '*') {
            const rest = pattern[2..];
            if (rest.len > 0 and rest[0] == '/') {
                if (globMatch(rest[1..], text)) return true;
                var k: usize = 0;
                while (k < text.len) : (k += 1) {
                    if (text[k] == '/' and globMatch(rest[1..], text[k + 1 ..])) return true;
                }
                return false;
            }
            var k: usize = 0;
            while (k <= text.len) : (k += 1) {
                if (globMatch(rest, text[k..])) return true;
            }
            return false;
        }
        var k: usize = 0;
        while (true) {
            if (globMatch(pattern[1..], text[k..])) return true;
            if (k >= text.len or text[k] == '/') return false;
            k += 1;
        }
    }
    if (text.len == 0) return false;
    if (pattern[0] == '?') {
        if (text[0] == '/') return false;
        return globMatch(pattern[1..], text[1..]);
    }
    if (pattern[0] != text[0]) return false;
    return globMatch(pattern[1..], text[1..]);
}

test "globMatch agrees with the shared case table" {
    const alloc = std.testing.allocator;
    const ioh = io();
    const data = readFile(ioh, alloc, "tools/glob_cases.txt") orelse return error.MissingGlobCases;
    defer alloc.free(data);
    var count: usize = 0;
    var lines = std.mem.splitScalar(u8, data, '\n');
    while (lines.next()) |line| {
        if (line.len == 0 or line[0] == '#') continue;
        var fields = std.mem.splitScalar(u8, line, '\t');
        const pattern = fields.next() orelse return error.BadCaseLine;
        const text = fields.next() orelse return error.BadCaseLine;
        const verdict = fields.next() orelse return error.BadCaseLine;
        const want = std.mem.eql(u8, verdict, "match");
        if (globMatch(pattern, text) != want) {
            std.debug.print("glob case failed: pattern={s} text={s} want={s}\n", .{ pattern, text, verdict });
            return error.GlobCaseFailed;
        }
        count += 1;
    }
    try std.testing.expect(count >= 20);
}
