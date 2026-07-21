// #Module is a closed definition. Unlisted fields are rejected, so there is
// no escape hatch for raw compiler flags.
package build

app: #Module & {
	kind:  "exe"
	root:  "src/main.zig"
	flags: ["-O3"]
}
