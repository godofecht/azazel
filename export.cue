package build

_modules: {
	"core":        core
	"app":         app
	"danzig":      danzig
	"danzig_gain": danzig_gain
	"danzig_test": danzig_test
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
