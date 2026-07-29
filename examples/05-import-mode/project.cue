// Two modules over an `import` edge.
//
//   mathlib (static, link: "import")  <-- app (exe)
//
// `mathlib` is marked link: "import", so it is not built as its own artifact.
// It merges into `app` as a Zig module, reached with @import("mathlib"). One
// compilation, no link step. Compare examples/02-lib-and-app, which links the
// same shape over the C ABI.
package build

mathlib: #Module & {
	kind: "static"
	root: "src/mathlib.zig"
	link: "import"
}

app: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	deps:    ["mathlib"]
	profile: "release"
}
