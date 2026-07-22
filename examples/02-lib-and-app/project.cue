// A static library and an executable that links it.
//
// `mathlib` takes the default profile ("debug"). `calc` overrides it.
package build

mathlib: #Module & {
	kind: "static"
	root: "src/mathlib.zig"
}

calc: #Module & {
	kind:    "exe"
	root:    "src/calc.zig"
	deps:    ["mathlib"]
	profile: "release"
}
