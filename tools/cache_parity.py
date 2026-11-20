#!/usr/bin/env python3
"""Compare cache-hit artifacts with clean-build artifacts on real corpus slices.

For each repo this builds the Azazel parity slice from scratch and records the
digest of every file in `zig-out`. It then runs `cache_build.sh` three times
against an empty store:

    miss       builds and stores the artifacts
    hit        runs with `zig-out` and the Zig cache removed, and must restore
    mutated    changes one source file the slice reaches, and must miss

The report passes when the hit equals the clean build, file for file, and the
mutated source moves the key. The slice workspace is the one `huge_corpus.py
--executable-parity` builds.

    tools/cache_parity.py --root DIR [--repo libvaxis --repo libxev]

The report goes to stdout as JSON. The exit status is 1 when any slice fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cache_closure  # noqa: E402
import huge_corpus  # noqa: E402

AZAZEL_ROOT = Path(__file__).resolve().parents[1]

# Sources a slice reaches, as paths from the slice workspace. Each gets an
# exported variable appended, which lands in the artifact's symbol table, so a
# stale hit would hand back a binary that lacks it. The first file is the
# slice's own probe. The second is upstream code outside the workspace.
MUTATIONS = {
    "libvaxis": ("src/vaxis_probe.zig", "../../src/Key.zig"),
    "libxev": ("src/xev_probe.zig", "../../src/main.zig"),
}
ADDITION = "\nexport var azazel_cache_mutation: u32 = 7;\n"


MH_MAGIC_64 = 0xFEEDFACF
LC_SYMTAB = 0x02
LC_UUID = 0x1B
LC_CODE_SIGNATURE = 0x1D
N_OSO = 0x66
CACHE_HASH = re.compile(rb"/o/[0-9a-f]{32}/")


def normalized_digest(data: bytes) -> str:
    """The sha256 of a file, with the Mach-O fields a linker varies blanked.

    Two clean builds of one source on macOS differ in three places and nowhere
    else: LC_UUID, the ad-hoc code signature that covers it, and the debug-map
    (N_OSO) entries, which hold the object file's mtime and a path with the
    Zig cache hash of the build. These are blanked before hashing, so the
    comparison sees code, data and symbols. Any other file hashes as is.
    """
    if len(data) < 32 or int.from_bytes(data[:4], "little") != MH_MAGIC_64:
        return hashlib.sha256(data).hexdigest()
    buffer = bytearray(data)
    count = int.from_bytes(buffer[16:20], "little")
    offset = 32
    for _ in range(count):
        cmd = int.from_bytes(buffer[offset:offset + 4], "little")
        size = int.from_bytes(buffer[offset + 4:offset + 8], "little")
        if cmd == LC_UUID:
            buffer[offset + 8:offset + 24] = bytes(16)
        elif cmd == LC_CODE_SIGNATURE:
            start = int.from_bytes(buffer[offset + 8:offset + 12], "little")
            length = int.from_bytes(buffer[offset + 12:offset + 16], "little")
            buffer[start:start + length] = bytes(length)
        elif cmd == LC_SYMTAB:
            symoff, nsyms, stroff, _strsize = (
                int.from_bytes(buffer[offset + 8 + 4 * i:offset + 12 + 4 * i], "little") for i in range(4)
            )
            for index in range(nsyms):
                entry = symoff + 16 * index
                if buffer[entry + 4] != N_OSO:
                    continue
                buffer[entry + 8:entry + 16] = bytes(8)
                strx = stroff + int.from_bytes(buffer[entry:entry + 4], "little")
                end = buffer.index(0, strx)
                text = bytes(buffer[strx:end])
                buffer[strx:end] = CACHE_HASH.sub(lambda m: b"/o/" + b"0" * 32 + b"/", text)
        offset += size
    return hashlib.sha256(bytes(buffer)).hexdigest()


def snapshot(directory: Path, normalize: bool = True) -> dict[str, str]:
    """Relative path to the sha256 of every file under `directory`."""
    found: dict[str, str] = {}
    for current, _, names in os.walk(directory):
        for name in sorted(names):
            path = Path(current) / name
            rel = path.relative_to(directory).as_posix()
            found[rel] = "link:" + os.readlink(path) if path.is_symlink() else (
                normalized_digest(path.read_bytes()) if normalize else hashlib.sha256(path.read_bytes()).hexdigest()
            )
    return dict(sorted(found.items()))


def differences(left: dict[str, str], right: dict[str, str]) -> list[str]:
    out = [f"only in first: {name}" for name in sorted(set(left) - set(right))]
    out += [f"only in second: {name}" for name in sorted(set(right) - set(left))]
    out += [f"differs: {name}" for name in sorted(set(left) & set(right)) if left[name] != right[name]]
    return out


def wipe(workdir: Path) -> None:
    for name in ("zig-out", ".zig-cache"):
        shutil.rmtree(workdir / name, ignore_errors=True)


def run(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def cache_build(workdir: Path, store: Path, env: dict[str, str]) -> tuple[str, str]:
    """Run cache_build.sh. Returns `HIT` or `MISS` or `REFUSED`, and the key."""
    env = dict(env, AZAZEL_PROJECT=str(workdir), SHARED=str(store))
    result = run(["sh", str(AZAZEL_ROOT / "cache_build.sh")], workdir, env)
    for line in result.stdout.splitlines():
        if line.startswith("[azazel-cache] HIT"):
            return "HIT", line.split()[-1]
        if line.startswith("[azazel-cache] MISS"):
            return "MISS", line.split()[2].rstrip(",")
    return "FAILED", result.stdout[-2000:]


def parity_entry(root: Path, repo: huge_corpus.Repo, scratch: Path) -> dict[str, object]:
    path = huge_corpus.ensure_clone(root, repo)
    huge_corpus.write_executable_parity_workspace(path, repo)
    huge_corpus.materialize_executable_parity_deps(path, repo)
    workdir = path / ".azazel" / "parity-work"
    resolution = huge_corpus.resolve_toolchain(repo)
    entry: dict[str, object] = {"name": repo.name, "zig": resolution.path, "passed": False}
    if not resolution.path:
        entry["error"] = resolution.diagnostic
        return entry

    zig_dir = str(Path(resolution.path).resolve().parent)
    env = os.environ.copy()
    env["PATH"] = zig_dir + os.pathsep + env["PATH"]
    env["ZIG_GLOBAL_CACHE_DIR"] = str(scratch / "global-cache")
    env["ZIG_LOCAL_CACHE_DIR"] = str(workdir / ".zig-cache")
    store = scratch / "store"
    store.mkdir(parents=True, exist_ok=True)

    generated = run(["sh", "gen_build_spec.sh"], workdir, env)
    if generated.returncode != 0:
        entry["error"] = "generation failed: " + generated.stdout[-2000:]
        return entry

    # Two clean builds. Their agreement says whether the build is repeatable at
    # all, which bounds what a cache hit can be expected to match.
    snapshots: list[dict[str, str]] = []
    for _ in range(2):
        wipe(workdir)
        built = run(["zig", "build"], workdir, env)
        if built.returncode != 0:
            entry["error"] = "clean build failed: " + built.stdout[-2000:]
            return entry
        snapshots.append(snapshot(workdir / "zig-out"))
    clean, clean_again = snapshots
    entry["clean_repeatable"] = clean == clean_again
    entry["clean_files"] = len(clean)

    wipe(workdir)
    first, first_key = cache_build(workdir, store, env)
    miss = snapshot(workdir / "zig-out")
    miss_raw = snapshot(workdir / "zig-out", normalize=False)
    wipe(workdir)
    second, second_key = cache_build(workdir, store, env)
    hit = snapshot(workdir / "zig-out")
    hit_raw = snapshot(workdir / "zig-out", normalize=False)
    entry.update(
        first_run=first,
        second_run=second,
        key=first_key,
        key_stable=first_key == second_key,
        miss_vs_clean=differences(clean, miss),
        hit_vs_clean=differences(clean, hit),
        hit_vs_miss=differences(miss, hit),
        hit_vs_miss_bytes=differences(miss_raw, hit_raw),
    )

    # A source the slice reaches changes: the key must move, the run must miss,
    # and the stored result must match a clean build of the changed tree.
    mutations = []
    for rel in MUTATIONS[repo.name]:
        target = workdir / rel
        original = target.read_text(encoding="utf-8")
        try:
            target.write_text(original + ADDITION, encoding="utf-8")
            wipe(workdir)
            miss_run, miss_key = cache_build(workdir, store, env)
            wipe(workdir)
            hit_run, _ = cache_build(workdir, store, env)
            mutated_hit = snapshot(workdir / "zig-out")
            wipe(workdir)
            rebuilt = run(["zig", "build"], workdir, env)
            mutated_clean = snapshot(workdir / "zig-out") if rebuilt.returncode == 0 else {}
        finally:
            target.write_text(original, encoding="utf-8")
        mutations.append(
            {
                "file": rel,
                "first_run": miss_run,
                "key_differs": miss_key != first_key,
                "second_run": hit_run,
                "hit_vs_clean": differences(mutated_clean, mutated_hit),
                "artifacts_differ_from_original": mutated_clean != clean,
            }
        )
    entry["mutations"] = mutations
    entry["passed"] = (
        entry["clean_repeatable"]
        and first == "MISS"
        and second == "HIT"
        and entry["key_stable"]
        and not entry["hit_vs_clean"]
        and not entry["miss_vs_clean"]
        and not entry["hit_vs_miss_bytes"]
        and all(
            m["first_run"] == "MISS"
            and m["key_differs"]
            and m["second_run"] == "HIT"
            and not m["hit_vs_clean"]
            and m["artifacts_differ_from_original"]
            for m in mutations
        )
    )
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="the corpus clone directory, as for huge_corpus.py --root")
    parser.add_argument("--repo", action="append", default=[], help="repo name; default libvaxis and libxev")
    parser.add_argument("--fetch-toolchains", action="store_true")
    args = parser.parse_args()
    huge_corpus.FETCH_TOOLCHAINS = args.fetch_toolchains
    repos = huge_corpus.select_repos(args.repo or ["libvaxis", "libxev"])
    report = []
    with tempfile.TemporaryDirectory(prefix="azazel-cache-parity-") as tmp:
        for repo in repos:
            scratch = Path(tmp) / repo.name
            scratch.mkdir()
            report.append(parity_entry(Path(args.root), repo, scratch))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(item["passed"] for item in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
