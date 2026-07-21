# 04-validation

What CUE catches, what it does not, and what the error text looks like.

## What it demonstrates

- Every rejection the schema performs, with the exact `cue` output.
- The one failure CUE cannot catch, and how it shows up instead.

## Run it

```sh
cd examples/04-validation
./check.sh
```

`check.sh` takes each file in `cases/`, drops it into a temporary directory
alongside `schema.cue` and `export.cue`, and runs `cue export -e build`.
Every case is expected to fail. The script exits non-zero if any of them
is accepted, so it works as a regression test on the schema.

## Layout

```
04-validation/
  schema.cue
  export.cue          maps a single module named `app`
  project.cue         the valid baseline
  gen_build_spec.sh
  check.sh
  cases/*.cue         one broken variant per file
  src/main.zig
```

## The cases

| Case | Change | Caught by |
|------|--------|-----------|
| `bad-kind` | `kind: "dylib"` | `#Kind` disjunction |
| `bad-profile` | `profile: "turbo"` | `#Profile` disjunction |
| `wrong-type` | `root: 42` | `root: string` |
| `deps-wrong-type` | `deps: "mathlib"` | `deps: [...string]` |
| `missing-kind` | no `kind` | incomplete value at export |
| `missing-root` | no `root` | incomplete value at export |
| `unknown-field` | `flags: ["-O3"]` | `#Module` is closed |

## Real output

```
$ ./check.sh
==============================================================
case: bad-kind
--------------------------------------------------------------
"dylib" is not in #Kind.
--------------------------------------------------------------
rejected by cue:
app.kind: 3 errors in empty disjunction:
app.kind: conflicting values "exe" and "dylib":
    ./project.cue:4:6
    ./project.cue:5:8
    ./schema.cue:3:11
    ./schema.cue:7:12
app.kind: conflicting values "shared" and "dylib":
    ./project.cue:4:6
    ./project.cue:5:8
    ./schema.cue:3:30
    ./schema.cue:7:12
app.kind: conflicting values "static" and "dylib":
    ./project.cue:4:6
    ./project.cue:5:8
    ./schema.cue:3:19
    ./schema.cue:7:12

==============================================================
case: bad-profile
--------------------------------------------------------------
"turbo" is not in #Profile.
--------------------------------------------------------------
rejected by cue:
app.profile: 2 errors in empty disjunction:
app.profile: 3 errors in empty disjunction:
app.profile: conflicting values "debug" and "turbo":
    ./project.cue:4:6
    ./project.cue:7:11
    ./schema.cue:4:11
    ./schema.cue:10:12
app.profile: conflicting values "release" and "turbo":
    ./project.cue:4:6
    ./project.cue:7:11
    ./schema.cue:4:21
    ./schema.cue:10:12

==============================================================
case: deps-wrong-type
--------------------------------------------------------------
deps is [...string]. A bare string is not a list of strings.
--------------------------------------------------------------
rejected by cue:
app.deps: 2 errors in empty disjunction:
app.deps: conflicting values "mathlib" and [...string] (mismatched types string and list):
    ./project.cue:4:6
    ./project.cue:7:8
    ./schema.cue:9:8
app.deps: conflicting values "mathlib" and [] (mismatched types string and list):
    ./project.cue:4:6
    ./project.cue:7:8
    ./schema.cue:9:23

==============================================================
case: missing-kind
--------------------------------------------------------------
kind has no default, so omitting it leaves the value incomplete.
--------------------------------------------------------------
rejected by cue:
build.modules.app.kind: incomplete value "exe" | "static" | "shared":
    ./export.cue:10:14

==============================================================
case: missing-root
--------------------------------------------------------------
root has no default either.
--------------------------------------------------------------
rejected by cue:
build.modules.app.root: incomplete value string:
    ./export.cue:11:14
    ./schema.cue:8:12

==============================================================
case: unknown-field
--------------------------------------------------------------
#Module is a closed definition. Unlisted fields are rejected, so there is
no escape hatch for raw compiler flags.
--------------------------------------------------------------
rejected by cue:
app.flags: field not allowed:
    ./project.cue:8:2

==============================================================
case: wrong-type
--------------------------------------------------------------
root must be a string.
--------------------------------------------------------------
rejected by cue:
app.root: conflicting values 42 and string (mismatched types int and string):
    ./project.cue:4:6
    ./project.cue:6:8
    ./schema.cue:8:12

==============================================================
All 7 cases rejected, as expected.
```

## Reading the errors

Two shapes come up.

**"conflicting values"** means you supplied a concrete value the schema
disallows. CUE unifies your value against every branch of the disjunction and
reports one conflict per branch, so a three-way `#Kind` produces three lines.
The last file:line pair in each block is the schema rule; the first is your
declaration.

**"incomplete value"** means you left a field unset that has no default. The
location points into `export.cue`, because that is where the field is first
read for output.

`cue vet` rejects all seven cases too, but it is vaguer about the incomplete
ones:

```
$ cue vet
some instances are incomplete; use the -c flag to show errors or -c=false to allow incomplete instances
```

`cue export -e build` names the field. Prefer it, or run `cue vet -c`.

## The failure CUE cannot catch

A module declared in `project.cue` but absent from `export.cue`'s `_modules`
map is silently dropped. Nothing errors.

```cue
// appended to project.cue
helper: #Module & {
	kind: "static"
	root: "src/helper.zig"
}
```

```
$ cue vet
$ echo $?
0

$ ./gen_build_spec.sh
Generated build_spec.zig
```

The generated spec still has one module:

```zig
pub const modules = [_]Module{
    .{
        .name = "app",
        .kind = .exe,
        .root = "src/main.zig",
        .deps = &.{},
        .optimize = .Debug,
    },
};
```

`src/helper.zig` does not even have to exist. `export.cue` is the list of
things that get built; `project.cue` is only where they are described. If a
module you added never appears in `zig-out`, check `_modules` first.

## Verified with

CUE v0.16.0.
