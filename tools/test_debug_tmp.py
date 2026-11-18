"""Temporary CI probe. Removed before review."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_fixture import Project, pipeline_available  # noqa: E402

APP = '\napp: #Module & {\n\tkind: "exe"\n\troot: "src/main.zig"\n}\n'


@unittest.skipUnless(pipeline_available(), "needs cue and zig")
class Probe(unittest.TestCase):
    def test_probe(self) -> None:
        report = []
        for label, dep in (
            ("nohint", '{name: "azazel-no-such-tool", kind: "tool"}'),
            ("hint", '{name: "azazel-no-such-tool", kind: "tool", hint: "h"}'),
        ):
            project = Project(f"system_deps: [\n\t{dep},\n]\n{APP}")
            self.addCleanup(project.close)
            gen = project.gen()
            spec = (project.root / "build_spec.zig").read_text()
            start = spec.index("pub const system_deps")
            report.append(f"== {label} gen rc={gen.returncode}\n{spec[start:start + 300]}")
            for args in (("doctor", "--summary", "all"), ("--summary", "all"), ("doctor",)):
                result = project.run("zig", "build", *args)
                report.append(f"-- zig build {' '.join(args)} rc={result.returncode}\n{result.stdout[-1500:]}")
        self.fail("\n".join(report))
