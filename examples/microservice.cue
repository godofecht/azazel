// Microservice: protocol lib shared across two services.
package build

protocol: #Module & {
	kind:    "static"
	root:    "src/protocol.zig"
	profile: "release"
}

gateway: #Module & {
	kind:    "exe"
	root:    "src/gateway.zig"
	deps:    ["protocol"]
	profile: "release"
}

worker: #Module & {
	kind:    "exe"
	root:    "src/worker.zig"
	deps:    ["protocol"]
	profile: "release"
}
