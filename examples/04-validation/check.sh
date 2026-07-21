#!/bin/sh
# Run every file in cases/ through CUE and show how it is rejected.
#
# Each case is combined with this directory's schema.cue and export.cue in a
# temporary directory, then exported. A case that exports cleanly is a bug in
# the schema, so this script exits non-zero if any case is accepted.
set -eu

cd "$(dirname "$0")"

if ! command -v cue >/dev/null 2>&1; then
	echo "cue not found on PATH. See https://cuelang.org/docs/introduction/installation/" >&2
	exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

failures=0

for case_file in cases/*.cue; do
	name=$(basename "$case_file" .cue)

	rm -rf "$tmp/work"
	mkdir -p "$tmp/work"
	cp schema.cue export.cue "$tmp/work/"
	cp "$case_file" "$tmp/work/project.cue"

	echo "=============================================================="
	echo "case: $name"
	echo "--------------------------------------------------------------"
	awk '/^\/\//{sub(/^\/\/ ?/,""); print; next} {exit}' "$case_file"
	echo "--------------------------------------------------------------"

	if (cd "$tmp/work" && cue export -e build) >"$tmp/out" 2>&1; then
		echo "ACCEPTED (expected a rejection)"
		cat "$tmp/out"
		failures=$((failures + 1))
	else
		echo "rejected by cue:"
		cat "$tmp/out"
	fi
	echo
done

echo "=============================================================="
if [ "$failures" -ne 0 ]; then
	echo "$failures case(s) were accepted when they should have been rejected."
	exit 1
fi

echo "All $(ls cases/*.cue | wc -l | tr -d ' ') cases rejected, as expected."
