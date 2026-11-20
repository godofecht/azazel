# Contributing to Azazel

Azazel treats the CUE model, generated Zig spec, and Zig executor as one public
contract. A schema feature is incomplete until it works through the entire
pipeline.

For changes to a module field, update `schema.cue`, `export.cue`,
`gen_build_spec.sh`, `build.zig`, tests, and the relevant documentation together.
Do not add executor behavior that cannot be represented by the build model, and
do not add model fields that are silently ignored downstream.

Before opening a pull request, run:

```sh
python3 azazel check
python3 azazel gen
cp build_spec.zig /tmp/build_spec.first
rm -f .build_spec.stamp
python3 azazel gen
diff -u /tmp/build_spec.first build_spec.zig
python3 azazel build
zig build test --summary all
python3 -m unittest discover -s tools -p 'test_*.py'
```

CI repeats the production path on Zig 0.14.1, 0.15.2, and 0.16.0. Changes to
`std.Build` compatibility must preserve all supported lanes unless the pull
request explicitly changes the support policy.

Real-project claims need executable evidence. Prefer adding or extending a
corpus target slice over claiming parity from an upstream `zig build` result.
Keep failure classifications explicit; `not-modeled`, missing toolchains, system
dependencies, and upstream API drift are not Azazel successes.

Cache changes must keep the key a function of every artifact-affecting input.
A new build feature that reads a file, a program or the environment needs either
a part of the key with a mutation test in `tools/test_cache_closure.py`, or a
refusal in `tools/cache_closure.py` with a test. Run
`tools/cache_parity.py --root DIR` against the libvaxis and libxev slices when
the key or the cache scripts change.

Keep pull requests focused. Large compatibility additions should name the real
project or build shape that requires them and include the command used to verify
the behavior.
