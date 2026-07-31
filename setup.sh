#!/bin/sh
# Azazel setup: check the toolchain, generate build_spec.zig, build, test.
#
# Safe to run repeatedly. Every step is idempotent. Exits non-zero on the
# first failure.
#
# Usage:
#   ./setup.sh                 check tools, generate, build, test
#   ./setup.sh --examples      also build and test everything under examples/
#   ./setup.sh --check-only    only report tool versions
#
# Environment:
#   ZIG=/path/to/zig           use a specific Zig binary (default: zig on PATH)
#   CUE=/path/to/cue           use a specific CUE binary (default: cue on PATH)
set -eu

cd "$(dirname "$0")"
ROOT=$(pwd)

ZIG=${ZIG:-zig}
CUE=${CUE:-cue}

WITH_EXAMPLES=0
CHECK_ONLY=0

for arg in "$@"; do
	case "$arg" in
	--examples) WITH_EXAMPLES=1 ;;
	--check-only) CHECK_ONLY=1 ;;
	-h | --help)
		sed -n '2,14p' "$0" | sed 's|^# \{0,1\}||'
		exit 0
		;;
	*)
		echo "unknown argument: $arg" >&2
		echo "try: $0 --help" >&2
		exit 2
		;;
	esac
done

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
fail() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

# --- prerequisites ---------------------------------------------------------

step "Checking prerequisites"

missing=0

if command -v "$ZIG" >/dev/null 2>&1; then
	ZIG_VERSION=$("$ZIG" version)
	say "  zig      $ZIG_VERSION   ($(command -v "$ZIG"))"
	case "$ZIG_VERSION" in
	0.14.* | 0.15.* | 0.16.*) ;;
	*) say "           note: tested lanes are 0.14.x, 0.15.x and 0.16.x. Others may work." ;;
	esac
	CACHE_SUFFIX=$(printf '%s' "$ZIG_VERSION" | tr -c 'A-Za-z0-9._-' '_')
	ZIG_CACHE_DIR=${ZIG_CACHE_DIR:-"$ROOT/.zig-cache-$CACHE_SUFFIX"}
	ZIG_GLOBAL_CACHE_DIR=${ZIG_GLOBAL_CACHE_DIR:-"$ROOT/.zig-cache-global-$CACHE_SUFFIX"}
	ZIG_LOCAL_CACHE_DIR=${ZIG_LOCAL_CACHE_DIR:-"$ZIG_CACHE_DIR"}
	export ZIG_GLOBAL_CACHE_DIR ZIG_LOCAL_CACHE_DIR
	say "           cache: $ZIG_CACHE_DIR"
else
	missing=1
	say "  zig      MISSING"
	say "           macOS:  brew install zig"
	say "           Linux:  https://ziglang.org/download/  (or your package manager)"
	say "           Any:    https://github.com/marler8997/zigup"
	say "           Already installed elsewhere? Run: ZIG=/path/to/zig $0"
fi

if command -v "$CUE" >/dev/null 2>&1; then
	CUE_VERSION=$("$CUE" version | head -1 | awk '{print $NF}')
	say "  cue      $CUE_VERSION   ($(command -v "$CUE"))"
else
	missing=1
	say "  cue      MISSING"
	say "           macOS:  brew install cue"
	say "           Go:     go install cuelang.org/go/cmd/cue@latest"
	say "           Any:    https://cuelang.org/docs/introduction/installation/"
	say "           Already installed elsewhere? Run: CUE=/path/to/cue $0"
fi

if command -v python3 >/dev/null 2>&1; then
	say "  python3  $(python3 --version 2>&1 | awk '{print $2}')   ($(command -v python3))"
else
	missing=1
	say "  python3  MISSING"
	say "           gen_build_spec.sh uses python3 to turn cue's JSON into Zig."
	say "           macOS:  brew install python"
	say "           Linux:  apt install python3  /  dnf install python3"
fi

[ "$missing" -eq 0 ] || fail "install the tools above, then run $0 again"

if [ "$CHECK_ONLY" -eq 1 ]; then
	say ""
	say "All prerequisites present."
	exit 0
fi

# --- root project ----------------------------------------------------------

# gen_build_spec.sh calls `cue` by name, so honour a CUE override by putting
# its directory first on PATH.
if [ "$CUE" != "cue" ]; then
	PATH="$(dirname "$(command -v "$CUE")"):$PATH"
	export PATH
fi

step "Generating build_spec.zig"
./gen_build_spec.sh

step "Building"
"$ZIG" build --cache-dir "$ZIG_CACHE_DIR"

step "Testing"
"$ZIG" build test --cache-dir "$ZIG_CACHE_DIR" --summary all

# --- examples --------------------------------------------------------------

if [ "$WITH_EXAMPLES" -eq 1 ]; then
	for dir in examples/*/; do
		[ -f "$dir/gen_build_spec.sh" ] || continue

		step "Example: $dir"
		cd "$ROOT/$dir"
		./gen_build_spec.sh
		if [ -f build.zig ]; then
			"$ZIG" build --cache-dir "$ZIG_CACHE_DIR"
			# Only run the test step if the example defines one.
			if grep -q 'b.step("test"' build.zig; then
				"$ZIG" build test --cache-dir "$ZIG_CACHE_DIR" --summary all
			fi
		fi
		if [ -f check.sh ]; then
			# Only the verdict here. Run ./check.sh directly for the detail.
			./check.sh | tail -1
		fi
		cd "$ROOT"
	done
fi

# --- done ------------------------------------------------------------------

say ""
say "Done."
say ""
say "  ./zig-out/bin/app          run the sample executable"
say "  \$EDITOR project.cue        declare your modules"
say "  ./gen_build_spec.sh        regenerate after every project.cue change"
say "  docs/WIKI.md               full reference"
