#!/bin/sh
# Azazel shared-cache build.
#
#   sh cache_build.sh [zig build arguments...]
#
# Computes the declared-input closure key (tools/cache_closure.py, CACHE.md),
# restores the artifacts stored under that key, or builds and stores them. A
# build whose inputs the key cannot name is refused with exit status 3 and
# nothing is read from or written to the store. AZAZEL_PROJECT names the project
# directory when it is not the directory holding this script.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PROJECT=${AZAZEL_PROJECT:-$HERE}
cd "$PROJECT"

KEY=$(sh "$HERE/cache_key.sh" "$@") || exit $?
ASSET="$KEY.tar"

MARKER=.azazel-cache-key

restore() { # <tarfile>
    rm -rf zig-out && mkdir -p zig-out && tar -xf "$1" -C zig-out
    # An entry carries the key it was stored under. A renamed or swapped file
    # is refused, and the marker is removed so zig-out matches a clean build.
    if [ "$(cat "zig-out/$MARKER" 2>/dev/null)" != "$KEY" ]; then
        rm -rf zig-out
        echo "[azazel-cache] entry does not carry key $KEY, rebuilding" >&2
        return 1
    fi
    rm -f "zig-out/$MARKER"
    echo "[azazel-cache] HIT  $KEY"
}

build_and_tar() { # <out-tar> [zig build arguments...]
    out=$1
    shift
    echo "[azazel-cache] MISS $KEY, building"
    sh gen_build_spec.sh
    zig build "$@"
    printf '%s' "$KEY" > "zig-out/$MARKER"
    tar -cf "$out" -C zig-out .
    rm -f "zig-out/$MARKER"
}

# Resolve the GitHub backend: explicit repo, else the current git remote.
REPO="${AZAZEL_CACHE_REPO:-}"
if [ -z "$REPO" ] && command -v gh >/dev/null 2>&1; then
    REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
fi
REL="${AZAZEL_CACHE_RELEASE:-cache}"

# Prefer the GitHub Releases backend when gh + a repo are available and SHARED
# was not explicitly requested.
if [ -z "${SHARED:-}" ] && [ -n "$REPO" ] && command -v gh >/dev/null 2>&1; then
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT HUP INT TERM
    if gh release download "$REL" --repo "$REPO" --pattern "$ASSET" --dir "$tmp" >/dev/null 2>&1 \
        && restore "$tmp/$ASSET"; then
        exit 0
    fi
    build_and_tar "$tmp/$ASSET" "$@"
    gh release view "$REL" --repo "$REPO" >/dev/null 2>&1 || \
        gh release create "$REL" --repo "$REPO" --title "azazel shared cache" \
            --notes "Content-addressed build artifacts keyed by the declared-input closure." >/dev/null 2>&1 || true
    if gh release upload "$REL" "$tmp/$ASSET" --repo "$REPO" --clobber >/dev/null 2>&1; then
        echo "[azazel-cache] uploaded $KEY to $REPO ($REL)"
    else
        echo "[azazel-cache] built $KEY (upload skipped: no write access to $REPO)"
    fi
    exit 0
fi

# Local-directory backend.
SHARED="${SHARED:-$HOME/.azazel-shared-cache}"
mkdir -p "$SHARED"
if [ -f "$SHARED/$ASSET" ] && restore "$SHARED/$ASSET"; then
    exit 0
fi
build_and_tar "$SHARED/$ASSET" "$@"
echo "[azazel-cache] stored $KEY in $SHARED"
