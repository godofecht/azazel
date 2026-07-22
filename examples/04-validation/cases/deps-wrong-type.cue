// deps is [...string]. A bare string is not a list of strings.
package build

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
	deps: "mathlib"
}
