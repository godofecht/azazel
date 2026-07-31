package build

toolchain: zig: {
	lanes: ["0.14", "0.15", "0.16"]
	preferred: "0.15"
}

core: #Module & {
	kind: "module"
	root: "src/core.zig"
}

app: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	deps:    ["core"]
	profile: "release"
}

danzig: #Module & {
	kind: "static"
	root: "src/danzig/root.zig"
}

danzig_gain: #Module & {
	kind: "shared"
	root: "examples/danzig-gain/root.zig"
	deps: ["danzig"]
}

danzig_test: #Module & {
	kind: "exe"
	root: "examples/danzig-test/root.zig"
	deps: ["danzig"]
}
