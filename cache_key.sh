#!/bin/sh
# Experimental Azazel cache key.
#
# This key is intentionally not advertised as a complete build-input closure.
# It covers the normalized model, reachable Zig source, the Azazel execution
# files, dependency identities, Zig version, and host identity. See CACHE.md for
# known gaps and promotion criteria.
set -eu
cd "$(dirname "$0")"

MODEL=$(cue export -e build)

SRC_HASHES=$(printf '%s' "$MODEL" | python3 -c '
import json, sys, os, re

IMPORT = re.compile(r"@import\(\s*\"([^\"]+)\"\s*\)")
roots = [m["root"] for m in json.load(sys.stdin)["modules"].values()]
seen, stack = set(), [os.path.normpath(r) for r in roots if os.path.isfile(r)]
while stack:
    f = stack.pop()
    if f in seen:
        continue
    seen.add(f)
    try:
        src = open(f, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    base = os.path.dirname(f)
    for spec in IMPORT.findall(src):
        if not spec.endswith(".zig"):
            continue
        cand = os.path.normpath(os.path.join(base, spec))
        if os.path.isfile(cand) and cand not in seen:
            stack.append(cand)
for f in sorted(seen):
    print(f)
' | while IFS= read -r f; do [ -f "$f" ] && shasum -a 256 "$f"; done)

# Changes to the schema, exporter, code generator, or Zig executor can change
# the artifact even when the resolved project model is unchanged.
ENGINE_HASHES=$(
    for f in schema.cue project.cue export.cue gen_build_spec.sh build.zig build.zig.zon; do
        [ -f "$f" ] && shasum -a 256 "$f"
    done
)

DEPS=$( [ -f build.zig.zon ] && grep -E '\.url|\.hash' build.zig.zon | sed 's/^[[:space:]]*//' | sort || true )
LANE=$(printf '%s' "$MODEL" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("toolchain",{}).get("zig",{}).get("preferred",""))')
ZIGV=$(zig version 2>/dev/null || echo unknown)
HOST=$(uname -sm 2>/dev/null || echo unknown)

printf '%s\n%s\n%s\n%s\nlane=%s\nzig=%s\nhost=%s\n' \
    "$MODEL" "$SRC_HASHES" "$ENGINE_HASHES" "$DEPS" "$LANE" "$ZIGV" "$HOST" \
    | shasum -a 256 | cut -d' ' -f1
