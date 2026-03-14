// Multi-library: shared math lib, static utils lib, app links both.
package build

math: #Module & {
	kind: "shared"
	root: "src/math.zig"
	profile: "release"
}

utils: #Module & {
	kind: "static"
	root: "src/utils.zig"
}

app: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	deps:    ["math", "utils"]
	profile: "release"
}
