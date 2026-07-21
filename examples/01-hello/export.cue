// Every module declared in project.cue must be listed here. The generator
// reads this map and nothing else.
package build

_modules: {
	"hello": hello
}

build: modules: {
	for k, v in _modules {
		(k): {
			kind:     v.kind
			root:     v.root
			deps:     v.deps
			optimize: profiles[v.profile].optimize
		}
	}
}
