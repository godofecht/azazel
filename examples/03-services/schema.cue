package build

#Kind:    "exe" | "static" | "shared"
#Profile: "debug" | "release"

#Module: {
	kind:     #Kind
	root:     string
	deps: [...string] | *[]
	profile:  #Profile | *"debug"
}

#Profiles: {
	debug: {
		optimize: "Debug"
	}
	release: {
		optimize: "ReleaseFast"
	}
}

profiles: #Profiles
