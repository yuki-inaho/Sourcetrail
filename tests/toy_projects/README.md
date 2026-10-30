# Checked-in toy projects

These deliberately small projects make the indexing contracts inspectable. The
design rationale, ADR links, scope, and retained baseline counterexample are
described in [the toy-problem specification](../../docs/contracts/toy-problems.md).

| Target | Input | Independent facts |
| --- | --- | --- |
| `TOY-CXX-001` | `fixtures/cxx/initial` and `updated`, C++17 | Two overloads, namespace membership, directed calls, shared header includes, declaration token ranges, deleted and renamed symbols |
| `TOY-PYTHON-001` | `fixtures/python/initial` and `updated`, frozen full Jedi indexer | Imports resolved to calls, inheritance, qualified calls, definition token ranges, deletion in the later of two source groups |

Each target has a checked-in `project.srctrlprj` and `expected.json`. The expected
facts are explicit and are not regenerated from the candidate's database. The
Python profile reflects the frozen adapter's mapping of class methods to
`NODE_FUNCTION` (`4096`); this is a profile-specific storage convention.
The pinned indexer's
[`beginVisitFuncdef`](https://github.com/CoatiSoftware/SourcetrailPythonIndexer/blob/eba5d0fe5059431bc479b2b36a814b6a9a21bde4/indexer.py#L308-L323)
records this kind for function definitions, including those inside classes.

The runner writes the compilation database and Python environment path for a
temporary project root. Source fixtures stay unchanged. The temporary roots
contain Japanese characters and spaces. Seven phases are observed for each
language: initial full index, no-op, deletion only, clean index of the deleted
state, rename/edit, clean index of the edited state, and a final no-op.

The two clean indexes use different roots. Full `schema25-exact-v1` observations
must agree for each of the four within-run comparisons, including signatures,
typed occurrences, file contents, completeness, and diagnostics. The authored
facts also apply to every phase, so two equally incomplete graphs cannot satisfy
the selected expected facts. Negative controls remove or reverse a call, drop
an overload or namespace membership, change a source range, and retain a stale
symbol; each must fail.

## Commands

Prepare the locked environments and build the real application first:

```sh
pixi run --locked build
pixi run --locked python tests/toy_projects/runner.py --output build/toy-projects/current
pixi run --locked python -m pytest -q tests/toy_projects
```

`--language cxx` or `--language python` selects one target. `--binary` and
`--python-environment` select the application and the Python interpreter examined
by the frozen indexer. Their defaults can also be supplied with
`SOURCETRAIL_BINARY` and `SOURCETRAIL_PYTHON_ENVIRONMENT`. Missing inputs fail.

For an equivalent refactor, retain a successful baseline and compare all seven
phase snapshots per language:

```sh
pixi run --locked python tests/toy_projects/runner.py --output build/toy-projects/before
# Rebuild after the implementation change.
pixi run --locked python tests/toy_projects/runner.py --output build/toy-projects/after --baseline build/toy-projects/before/summary.json
```

To run the pytest/CTest gate and the same baseline comparison in one execution,
set `SOURCETRAIL_TOY_BASELINE` to the baseline summary path when invoking
`pixi run --locked test-toys` or `pixi run --locked verify`. This optional baseline
must be successful; the normal CI run performs the within-run comparisons without
requiring an external historical receipt.

`--record-failures` collects remaining phases after an expected-fact or equality
failure, retaining a failed status and nonzero exit code. It is useful for a
pre-existing counterexample; such a receipt is rejected as an equivalence
baseline. Intentional corrections require a separate review of the exact delta.
`--binary-source-revision` records a caller-declared revision for a compiled
binary; the runner also hashes the executable and never infers its source from
the current working tree.

Each output directory contains `summary.json` and per-language snapshots, raw
databases, process logs, and any comparison diffs. Raw databases are debugging
receipts, not byte-for-byte golden files. The summary hashes inputs, expected
facts, snapshots, the runner, and its semantic comparison tool. A reused output
directory receives a failed receipt before verification begins, so a failed or
interrupted rerun cannot leave an earlier successful status. Existing baseline
receipts without the newer tool hashes remain readable. For pytest,
`SOURCETRAIL_TOY_OUTPUT` selects a persistent
output directory; otherwise receipts are kept in pytest's temporary directory.
Linux execution is currently covered. These fixtures do not establish modern
Python/C++ syntax support, Rust indexing, GUI equivalence, or all-input proofs.
