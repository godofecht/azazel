"""A throwaway Azazel project for end-to-end tests.

It copies the canonical pipeline files into a temporary directory, so a test
can write its own project.cue and run the real `cue export`, generator and
`zig build` against it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

AZAZEL_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_FILES = ("azazel", "build.zig", "schema.cue", "gen_build_spec.sh", "compat.zig", "build_spec_test.zig")

EXPORT_CUE = """package build

_modules: {
%s}

_toolchain: toolchain
_packages: packages
_options: options
_system_deps: system_deps

build: modules: {
	for k, v in _modules {
		(k): {
			kind: v.kind
			artifact_name: (v & {artifact_name: *k | string}).artifact_name
			root: v.root
			deps: v.deps
			link: v.link
			pre: v.pre
			post: v.post
			install_dirs: v.install_dirs
			pkg_library_paths: v.pkg_library_paths
			pkg_imports: v.pkg_imports
			pkg_artifacts: v.pkg_artifacts
			build_options: v.build_options
			option_values: v.option_values
			gen_imports: v.gen_imports
			build_options_import: v.build_options_import
			native: v.native
			optimize: profiles[v.profile].optimize
		}
	}
}

build: toolchain: _toolchain
build: packages: _packages
build: options: _options
build: system_deps: _system_deps
"""


def pipeline_available() -> bool:
    return shutil.which("cue") is not None and shutil.which("zig") is not None


class Project:
    def __init__(self, project_cue: str, modules: tuple[str, ...] = ("app",), export_cue: str | None = None) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="azazel-test-")
        self.root = Path(self._tmp.name).resolve()
        for name in PIPELINE_FILES:
            shutil.copy2(AZAZEL_ROOT / name, self.root / name)
        (self.root / "src").mkdir()
        self.write("src/main.zig", "pub fn main() void {}\n")
        self.write("project.cue", "package build\n\n" + project_cue)
        listing = "".join(f'\t"{name}": {name}\n' for name in modules)
        self.write("export.cue", export_cue if export_cue is not None else EXPORT_CUE % listing)

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run(self, *argv: str, path_prefix: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if path_prefix is not None:
            env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            list(argv),
            cwd=self.root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def gen(self) -> subprocess.CompletedProcess[str]:
        return self.run("sh", "gen_build_spec.sh")

    def zig_build(self, *args: str, path_prefix: Path | None = None) -> subprocess.CompletedProcess[str]:
        generated = self.gen()
        if generated.returncode != 0:
            return generated
        return self.run("zig", "build", *args, path_prefix=path_prefix)

    def close(self) -> None:
        self._tmp.cleanup()
