// Two clusters over an ABI boundary.
//
//   circle, square  --import-->  geometry (static, abi) --+
//                                                          +--> app (exe)
//   mean, spread    --import-->  stats    (static, abi) --+
//
// The leaf modules are link: "import": each compiles into its cluster head, not
// into its own artifact. Each head is link: "abi", so it becomes one static
// library that `app` links over the C ABI. A change inside a cluster recompiles
// only that cluster and relinks `app`. The other cluster stays cached.
//
// This is the shape to reach for on a large project: a handful of clusters,
// each an internal `import` graph, linked to each other over `abi`.
package build

// --- geometry cluster ---
circle:   #Module & { kind: "static", root: "src/circle.zig", profile: "release", link: "import" }
square:   #Module & { kind: "static", root: "src/square.zig", profile: "release", link: "import" }
geometry: #Module & { kind: "static", root: "src/geometry.zig", profile: "release", link: "abi", deps: ["circle", "square"] }

// --- stats cluster ---
mean:   #Module & { kind: "static", root: "src/mean.zig", profile: "release", link: "import" }
spread: #Module & { kind: "static", root: "src/spread.zig", profile: "release", link: "import", deps: ["mean"] }
stats:  #Module & { kind: "static", root: "src/stats.zig", profile: "release", link: "abi", deps: ["mean", "spread"] }

// --- application ---
app: #Module & { kind: "exe", root: "src/main.zig", profile: "release", deps: ["geometry", "stats"] }
