// One executable. No dependencies. Default profile.
//
// `deps` and `profile` are omitted, so the schema fills them in with
// [] and "debug".
package build

hello: #Module & {
	kind: "exe"
	root: "src/main.zig"
}
