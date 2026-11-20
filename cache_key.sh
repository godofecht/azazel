#!/bin/sh
# Print the Azazel cache key for this project, or the reasons it is not cacheable.
#
#   sh cache_key.sh [zig build arguments...]
#   sh cache_key.sh --explain [zig build arguments...]
#
# The key is computed by tools/cache_closure.py from the declared-input closure
# described in CACHE.md. AZAZEL_PROJECT names the project directory when it is
# not the directory holding this script. Exit status 3 means the build is not
# cacheable.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PROJECT=${AZAZEL_PROJECT:-$HERE}
MODE=key
if [ "${1:-}" = "--explain" ]; then
    MODE=explain
    shift
fi
exec python3 "$HERE/tools/cache_closure.py" "$MODE" --project "$PROJECT" -- "$@"
