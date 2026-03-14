// Minimal: single executable, no deps, debug mode (default).
package build

app: #Module & {
	kind: "exe"
	root: "src/main.zig"
}
