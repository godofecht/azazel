package build

#Kind:    "exe" | "static" | "shared" | "module"
#Profile: "debug" | "release"
#ZigLane: "0.14" | "0.15" | "0.16" | "0.17"
#OptionType: "bool" | "string" | "u32"

// How a module is consumed by the things that depend on it.
//
//   abi    a separately compiled artifact linked over the C ABI. Symbols cross
//          the edge as `pub export fn` / `extern fn`. Required for shared
//          libraries and for any C or C++ interop.
//   import merged into each dependent as a plain Zig module, reached with
//          `@import("<name>")`. One compilation, no link step. Much faster to
//          rebuild, and the only sensible choice for pure Zig-to-Zig edges.
//
// Default is `abi` so existing projects build unchanged.
#Link: "abi" | "import"

#Command: {
	argv: [...string]
}

#InstallDir: {
	source_dir: string
	install_dir: string | *"bin"
	install_subdir: string
}

#PackageLibraryPath: {
	package: string
	path: string | *""
	os?: string
	arch?: string
}

#PackageImport: {
	alias:   string
	package: string
	module:  string
	pass_target: bool | *true
	pass_optimize: bool | *true
	backend?: string

	// A `fields` string-list option passed to the dependency, for packages
	// that select which data tables to compile in (e.g. uucode's Unicode
	// property fields). Emitted as `.fields = @as([]const []const u8, ...)`
	// only when non-empty, so ordinary imports are unaffected.
	fields: [...string] | *[]
}

#PackageArtifact: {
	package: string
	artifact: string
	pass_target: bool | *true
	pass_optimize: bool | *true
	backend?: string
}

// A literal, typed value injected into a module's build-options module (the
// one imported under build_options_import). Unlike #Option, which surfaces a
// CLI flag, an #OptionValue is a fixed value the build config supplies so a
// module that does @import("<options>") compiles without the project's own
// build.zig. Used to reproduce generated options like tigerbeetle's
// vsr_options. `kind` selects which typed field is emitted.
#OptionValue: {
	name: string
	kind: "bool" | "string" | "u32" | "opt_commit"
	bool_value:   bool | *false
	string_value: string | *""
	u32_value:    uint32 | *0
	// opt_commit emits a ?[40]u8: a 40-char hex string, or "" for null.
	commit: string | *""
}

#Package: {
	url?: string
	hash?: string
	path?: string
	lazy: bool | *false
}

// One argument to a generated module's host tool. `literal` is passed verbatim;
// `input_file` is a repo path passed as a build-graph file dependency (so the
// run reruns when it changes); `output_file` names a file the tool writes,
// whose path the build graph captures.
#GenArg: {
	kind:  "literal" | "input_file" | "output_file"
	value: string
}

// A module produced by compiling a host tool from the repo, running it, and
// importing the file it writes. This reproduces a repo's codegen step (e.g.
// zls compiles src/tools/config_gen.zig, runs it, and imports the emitted
// version_data.zig as a module) without invoking the repo's own build.zig.
#GeneratedImport: {
	alias:     string   // @import name the consuming module uses
	tool_root: string   // host tool source (.zig), built for the host
	tool_name: string   // produced host executable's name
	args: [...#GenArg]
	output:    string   // the output_file arg whose written file is the module root
}

// One file a generator produces.
#GeneratedOutput: {
	// For a `tool` or `command` generator this is the value of the
	// `output_file` argument that names the file, or the `stdout` capture name.
	// For a `package` generator it is a label for the exported path.
	name: string & !=""

	// Install the file under the prefix at this relative path, for example
	// "share/man/man1/tool.1". Omit it for files only the build consumes.
	install?: string
}

// A build step that produces files, declared once and consumed by any module.
//
// Exactly one producer is set:
//
//   tool     a Zig source file compiled for the host and run
//   command  a program on PATH, such as `wayland-scanner` or `scdoc`
//   package  a path a `build.zig.zon` dependency exports with
//            `addNamedLazyPath`, such as the tables uucode generates
//
// `args` are passed in order. An `output_file` argument must match an entry in
// `outputs`. `stdin` feeds a repo file to the generator, and `stdout` captures
// what it prints as the named output.
#Generated: {
	tool?: {
		root: string
		name: string
	}
	command?: [string, ...string]
	package?: {
		package:    string
		named_path: string
		pass_target:   bool | *true
		pass_optimize: bool | *true
		backend?: string
		fields: [...string] | *[]

		// Must match the optimize mode of the module that imports the same
		// package, so both resolve to one dependency instance.
		optimize: "Debug" | "ReleaseFast" | "ReleaseSafe" | "ReleaseSmall" | *"Debug"
	}

	args: [...#GenArg] | *[]
	stdin?:  string
	stdout?: string
	outputs: [#GeneratedOutput, ...#GeneratedOutput]
}

// How a module consumes one generated output.
//
//   import    a Zig module, reached with `@import("<alias>")`
//   embed     any file, reached with `@embedFile("<alias>")`
//   c_source  a C source file compiled into the module
//   include   the output's directory is added to the C include path
#GeneratedUse: {
	from:   string
	output: string
	as:     "import" | "embed" | "c_source" | "include"

	// Required for `import` and `embed`.
	alias: string | *""
}

#Option: {
	name: string
	type: #OptionType
	description: string | *""
	default?: bool | string | int
}

#Native: {
	c_sources: [...string] | *[]
	include_dirs: [...string] | *[]
	system_include_dirs: [...string] | *[]
	library_paths: [...string] | *[]
	object_files: [...string] | *[]
	system_libs: [...string] | *[]
	pkg_config_libs: [...string] | *[]
	frameworks: [...string] | *[]
	link_libc: bool | *false
	link_libcpp: bool | *false
}

#Module: {
	kind:     #Kind
	root:     string

	// The produced artifact's name. Defaults to the module key. Set it when the
	// built exe or library should carry a name distinct from the module's graph
	// and `@import` name, e.g. a static `lib:xev` alongside a `module:xev`
	// import that both compile from one project.
	artifact_name?: string

	deps: [...string] | *[]
	profile:  #Profile | *"debug"
	link:     #Link | *"abi"
	post: [...#Command] | *[]
	pre: [...#Command] | *[]
	install_dirs: [...#InstallDir] | *[]
	pkg_library_paths: [...#PackageLibraryPath] | *[]
	pkg_imports: [...#PackageImport] | *[]
	pkg_artifacts: [...#PackageArtifact] | *[]
	build_options: [...string] | *[]
	option_values: [...#OptionValue] | *[]
	gen_imports: [...#GeneratedImport] | *[]
	generated: [...#GeneratedUse] | *[]
	build_options_import: string | *"build-options"
	native: #Native | *{}

	// A shared library is an ABI artifact by definition.
	if kind == "shared" {
		link: "abi"
	}

	// A module-only target has no artifact to link, so dependents consume it as
	// an import.
	if kind == "module" {
		link: "import"
	}
}

// A host operating system name, spelled the way Zig spells `std.Target.Os.Tag`.
#Os: "linux" | "macos" | "windows" | "freebsd" | "netbsd" | "openbsd"

// Something the machine must provide before the build can run.
//
//   tool         a program on PATH, such as `wayland-scanner`
//   pkg_config   a library known to pkg-config, probed with `--exists`
//   library      a system library the linker must find, probed with `-l<name>`
//   framework    an Apple framework, probed with `-framework <name>`
//   header       a C header, probed with `#include <name>`
//   include_dir  a directory that must exist; it is also searched by header probes
//
// `os` limits the requirement to those operating systems. A tool is matched
// against the host, everything else against the build target. An empty list
// means every platform.
#SystemDep: {
	name: string & !=""
	kind: "tool" | "pkg_config" | "library" | "framework" | "header" | "include_dir"
	os: [...#Os] | *[]

	// pkg_config only: passed as `--atleast-version`.
	min_version?: string

	// Shown when the requirement is missing, e.g. an install command.
	hint: string | *""
}

#Profiles: {
	debug: {
		optimize: "Debug"
	}
	release: {
		optimize: "ReleaseFast"
	}
}

#Toolchain: {
	zig: {
		// Azazel is maintained as explicit Zig API lanes. A project can narrow
		// this list when it relies on one lane's std.Build surface.
		lanes: [...#ZigLane] | *["0.14", "0.15", "0.16"]
		preferred: #ZigLane | *"0.15"
	}
}

profiles: #Profiles
toolchain: #Toolchain | *{}
packages: [string]: #Package | *{}
options: [...#Option] | *[]
system_deps: [...#SystemDep] | *[]
generated: [string]: #Generated
