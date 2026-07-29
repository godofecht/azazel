package build

#Kind:    "exe" | "static" | "shared"
#Profile: "debug" | "release"

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

#Module: {
	kind:     #Kind
	root:     string
	deps: [...string] | *[]
	profile:  #Profile | *"debug"
	link:     #Link | *"abi"

	// A shared library is an ABI artifact by definition.
	if kind == "shared" {
		link: "abi"
	}
}

#Profiles: {
	debug: {
		optimize: "Debug"
	}
	release: {
		optimize: "ReleaseFast"
	}
}

profiles: #Profiles
