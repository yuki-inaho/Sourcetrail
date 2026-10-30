# External indexer outcome toy

`TOY-EXTERNAL-001` exercises the actual application's Custom Source Group and its
normal scheduler, process launcher, candidate storage, finalization, and CLI exit.
Its design follows [ADR-0007](../../docs/adr/0007-external-indexer-outcomes.md) and
[EXECUTION-001](../../docs/contracts/external-indexing.md).

## Why this artificial target

The source tree already has successful C++ and Python semantic fixtures. A tiny
executable with a declared exit behavior isolates the complementary process
boundary without making a real parser fail accidentally. The checked-in
`fixtures/expected.json` describes independent expectations. `fixtures/driver.py`
is copied to executable `.toy` inputs with the current Pixi Python interpreter as
their shebang. The Custom command is `"%{SOURCE_FILE_PATH}"`: quoting preserves a
path containing spaces when the legacy no-argument command-line parser runs.

| Case | Observation required |
| --- | --- |
| Missing executable | CLI 1, no command counted successful, no fixture receipt |
| Exit 7 | Fixture proves it ran and returned 7; Sourcetrail exits 1 and counts zero successes |
| Stderr with exit 0 | Warning remains observable, CLI 0, successful command count unchanged |
| Silent exit 0 | CLI 0; the fixture writes no graph, so zero indexed files explicitly remain possible |
| Mixed serial / parallel | Both commands run, exactly one succeeds, whole run exits 1 |
| Accepted C++ index then mixed failure | Exact accepted semantic snapshot remains; candidate and worker DBs are removed |
| Retry after failure | Successful replacement is visible, old symbol disappears, result equals a clean C++ rebuild |

Each executed `.toy` writes its own receipt containing mode, exit code, source,
cwd, arguments and PID. Receipts prevent a failed fixture setup from looking like
a correctly exercised nonzero-exit case. Projects, selected executable inputs and
working directories include spaces and Japanese characters. The preserved index
is made by the real C++ parser; no fake database replaces the parser's output.

## Run and inspect

```sh
pixi run --locked test-external-indexer
# Observe the same requirements against another already built binary:
pixi run --locked python tests/external_indexer/harness.py \
  --binary /absolute/path/to/Sourcetrail --output build/external-indexer/manual
```

The harness always writes an initial failed summary before doing work. It retains
per-process logs, observations and semantic snapshots, and returns 1 if any
requirement fails. It does not turn an old implementation's failure into a passing
test. `--binary-source-revision` is explicitly caller-declared provenance; the
binary, harness and fixture hashes identify actual bytes separately.

`database_state` distinguishes an absent DB, `uninitialized-empty` tables left by
project initialization after first-candidate rejection, and an accepted
`schema-25` index. The uninitialized exception requires exactly the known table
and column names, no rows (including metadata), only the known occurrence primary
key index, and passing SQLite integrity checks. It is never exported as a semantic snapshot. Nonempty
unversioned data, schema drift and corrupt files fail; the semantic snapshot
reader itself remains strict. A failed update must retain the real seed snapshot,
so absence or an empty placeholder cannot satisfy index preservation.

CTest writes receipts under `build/external-indexer/current`; `SOURCETRAIL_BINARY`
and `SOURCETRAIL_EXTERNAL_OUTPUT` override executable/output locations. `pytest`
also runs negative controls for false exit success, incorrect counts, absent or
incorrect fixture execution, retained candidate files and unexpected output.

The fixture is Linux-only with the current Pixi environment. No-output exit 0 is
deliberate compatibility characterization, not an assertion of semantic index
completeness. Timeouts, cancellation, corrupt output, parser protocol negotiation
and crash-atomic database publication are separate acceptance work.
