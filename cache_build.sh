#!/bin/sh
# azazel shared-cache build: compute the model-derived key, and if that exact
# build is already in a shared artifact store, restore its output and skip the
# build entirely. Otherwise build, then store the output under the key. The
# store is a directory ($SHARED) that in a real setup is a network/object store
# shared across a team and CI — the transferable half of a remote cache, with
# the key computed from the pinned model instead of discovered by compiling.
set -eu
cd "$(dirname "$0")"
SHARED="${SHARED:-$HOME/.azazel-shared-cache}"
mkdir -p "$SHARED"

KEY=$(sh cache_key.sh)
ART="$SHARED/$KEY.tar"

if [ -f "$ART" ]; then
    echo "[azazel-cache] HIT  $KEY"
    rm -rf zig-out && mkdir -p zig-out && tar -xf "$ART" -C zig-out
    exit 0
fi

echo "[azazel-cache] MISS $KEY — building"
sh gen_build_spec.sh
zig build
tar -cf "$ART" -C zig-out .
echo "[azazel-cache] stored $KEY"
