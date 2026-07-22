// The library half of the example.
//
// `deps` in project.cue is a *link* edge. It does not create a Zig module
// import. Anything a dependent needs to call must cross the boundary as an
// exported C-ABI symbol.

pub export fn mathlib_add(a: i32, b: i32) i32 {
    return a + b;
}

pub export fn mathlib_mul(a: i32, b: i32) i32 {
    return a *% b;
}

pub export fn mathlib_clamp(v: i32, lo: i32, hi: i32) i32 {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}
