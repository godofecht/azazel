package build

toolchain: zig: {
	lanes: ["0.14", "0.15", "0.16"]
	preferred: "0.15"
}

core: #Module & {
	kind: "module"
	root: "src/core.zig"
}

// A static library built from the same source as the `core` module. Its
// artifact is named `core` (libcore.a) even though its graph key is `core_lib`,
// the decoupling from issue #36.
core_lib: #Module & {
	kind:          "static"
	root:          "src/core.zig"
	artifact_name: "core"
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
