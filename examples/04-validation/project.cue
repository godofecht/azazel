// The baseline. Every file in cases/ is a broken variant of this one.
package build

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
}
