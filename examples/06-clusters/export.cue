package build

_modules: {
	"circle":   circle
	"square":   square
	"geometry": geometry
	"mean":     mean
	"spread":   spread
	"stats":    stats
	"app":      app
}

build: modules: {
	for k, v in _modules {
		(k): {
			kind:     v.kind
			root:     v.root
			deps:     v.deps
			link:     v.link
			optimize: profiles[v.profile].optimize
		}
	}
}
