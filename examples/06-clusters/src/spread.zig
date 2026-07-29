const mean = @import("mean");
pub fn variance(xs: []const f64) f64 {
    const m = mean.of(xs);
    var s: f64 = 0;
    for (xs) |x| s += (x - m) * (x - m);
    return s / @as(f64, @floatFromInt(xs.len));
}
