// The `stats` cluster. `spread` itself imports `mean`, so the whole cluster is
// one compilation regardless of how its members depend on each other.
const mean = @import("mean");
const spread = @import("spread");

pub export fn stats_variance(xs: [*]const f64, len: usize) f64 {
    return spread.variance(xs[0..len]);
}
export fn stats_mean(xs: [*]const f64, len: usize) f64 {
    return mean.of(xs[0..len]);
}
