// An `import` dependency is ordinary Zig. No `pub export fn`, no C ABI. The
// dependent reaches these with @import("mathlib").
pub fn add(a: i32, b: i32) i32 {
    return a + b;
}

pub fn mul(a: i32, b: i32) i32 {
    return a * b;
}
