package build

_modules: {
	"app": app
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
