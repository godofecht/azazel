package build

core: #Module & {
	kind: "static"
	root: "src/core.zig"
}

app: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	deps:    ["core"]
	profile: "release"
}
