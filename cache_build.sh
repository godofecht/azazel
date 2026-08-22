#!/bin/sh
# Experimental Azazel shared-cache build.
#
# The core Azazel build path is production-supported. Shared artifact caching is
# deliberately opt-in until the cache key can prove a complete declared-input
# closure for every build feature. See CACHE.md.
set -eu
cd "$(dirname "$0")"

if [ "${AZAZEL_EXPERIMENTAL_CACHE:-0}" != "1" ]; then
    echo "error: shared cache is experimental and disabled by default" >&2
    echo "set AZAZEL_EXPERIMENTAL_CACHE=1 only after reading CACHE.md" >&2
    exit 2
fi

KEY=$(sh cache_key.sh)
ASSET="$KEY.tar"

restore() { # <tarfile>
    rm -rf zig-out && mkdir -p zig-out && tar -xf "$1" -C zig-out
    echo "[azazel-cache] HIT  $KEY"
}

build_and_tar() { # <out-tar>
    echo "[azazel-cache] MISS $KEY — building"
    sh gen_build_spec.sh
    zig build
    tar -cf "$1" -C zig-out .
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
    if gh release download "$REL" --repo "$REPO" --pattern "$ASSET" --dir "$tmp" >/dev/null 2>&1; then
        restore "$tmp/$ASSET"
        exit 0
    fi
    build_and_tar "$tmp/$ASSET"
    gh release view "$REL" --repo "$REPO" >/dev/null 2>&1 || \
        gh release create "$REL" --repo "$REPO" --title "azazel shared cache" \
            --notes "Experimental content-addressed build artifacts." >/dev/null 2>&1 || true
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
if [ -f "$SHARED/$ASSET" ]; then
    restore "$SHARED/$ASSET"
    exit 0
fi
build_and_tar "$SHARED/$ASSET"
echo "[azazel-cache] stored $KEY in $SHARED"
