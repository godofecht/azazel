package build

toolchain: zig: {
	lanes: ["0.14", "0.15", "0.16"]
	preferred: "0.15"
}

// Host requirements for this repository. `zig build` checks them before any
// artifact compiles, and `azazel doctor` checks them without building.
system_deps: [
	{name: "python3", kind: "tool", hint: "gen_build_spec.sh renders build_spec.zig with python3"},
	{name: "cue", kind: "tool", hint: "https://cuelang.org/docs/install/"},
]

// The package version, read out of build.zig.zon before `app` compiles.
generated: build_info: {
	command: ["python3"]
	args: [
		{kind: "input_file", value: "tools/gen/build_info.py"},
		{kind: "input_file", value: "build.zig.zon"},
		{kind: "output_file", value: "build_info.zig"},
	]
	outputs: [{name: "build_info.zig"}]
}

// Nested packages. The danzig core and each example have their own directory.
// A build can name a slice of them: `azazel build --slice 'examples/*'`, or
// `azazel build --subproject danzig_gain`. Example artifacts install under
// their own output directory.
subprojects: {
	danzig: {path: "src/danzig", description: "the vendored danzig audio core"}
	danzig_gain: {path: "examples/danzig-gain", output_dir: "examples/danzig-gain", description: "a gain plugin built on danzig"}
	danzig_test: {path: "examples/danzig-test", output_dir: "examples/danzig-test", description: "a test host for danzig"}
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
	generated: [{from: "build_info", output: "build_info.zig", as: "import", alias: "build_info"}]
}

danzig: #Module & {
	kind: "static"
	subproject: "danzig"
	root: "src/danzig/root.zig"
}

danzig_gain: #Module & {
	kind: "shared"
	subproject: "danzig_gain"
	root: "examples/danzig-gain/root.zig"
	deps: ["danzig"]
}

danzig_test: #Module & {
	kind: "exe"
	subproject: "danzig_test"
	root: "examples/danzig-test/root.zig"
	deps: ["danzig"]
}
