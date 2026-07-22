// Two executables over a shared dependency graph.
//
//   protocol (static)  <-- gateway (exe, release)
//        ^                    |
//        |                    v
//        +------------------ codec (shared)
//        ^
//        |
//   worker (exe, debug)
//
// `protocol` is linked by three modules. `codec` is a shared library, so it
// lands in zig-out/lib as a .dylib/.so rather than a .a.
package build

protocol: #Module & {
	kind:    "static"
	root:    "src/protocol.zig"
	profile: "release"
}

codec: #Module & {
	kind:    "shared"
	root:    "src/codec.zig"
	deps:    ["protocol"]
	profile: "release"
}

gateway: #Module & {
	kind:    "exe"
	root:    "src/gateway.zig"
	deps:    ["protocol", "codec"]
	profile: "release"
}

// Left on the default profile so the two binaries differ.
worker: #Module & {
	kind: "exe"
	root: "src/worker.zig"
	deps: ["protocol"]
}
