// "turbo" is not in #Profile.
package build

app: #Module & {
	kind:    "exe"
	root:    "src/main.zig"
	profile: "turbo"
}
