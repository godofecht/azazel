// The `geometry` cluster. It imports its member modules (compiled into this one
// artifact) and exposes a single C-ABI entry point that `app` links against.
const circle = @import("circle");
const square = @import("square");

pub export fn geometry_total(r: f64, side: f64) f64 {
    return circle.area(r) + square.area(side);
}
