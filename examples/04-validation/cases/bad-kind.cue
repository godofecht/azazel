// "dylib" is not in #Kind.
package build

app: #Module & {
	kind: "dylib"
	root: "src/main.zig"
}
