# Development and indexing tests with Pixi

The checked-in `pixi.toml` and `pixi.lock` provide a Linux x86-64 environment for
building Sourcetrail with both C/C++ and Python indexing enabled. The same tasks
run locally and in `.github/workflows/pixi-tests.yml`.

The [internal documentation index](README.md) connects architecture, ADRs,
executable contracts, bounded TLA+ models, and review reports. To run the complete
verification gate, including the separate Java and portable C++/Rust environments:

```sh
pixi install --locked --all
pixi run --locked verify
```

`pixi run --locked test-contracts` selects the C++ planning/source-group contracts
and the Python verification-tool and graph-equivalence tests.
`pixi run --locked verify-docs` checks documentation traceability.
`pixi run -e formal --locked verify-models` checks the bounded TLA+ model and its
required negative control. This environment fixes OpenJDK 17 and downloads the
official TLC 1.7.4 JAR with a pinned SHA-256. See the
[model scope and limits](contracts/formal/README.md); these checks do not prove
the entire application or advertise support for new language versions.

`pixi run --locked test-toys` runs the checked-in synthetic C++ and Python projects
with authored expected facts, seven observations per language, and exact graph
comparisons. See [toy design, rationale and limits](contracts/toy-problems.md).
`pixi run -e portability --locked verify-portability` builds the standard-library
core without Qt, Boost or LLVM, then checks the production C++ planner and a Rust
reference port against ten explicit vectors and 32,768 independently computed
cases. The separate environment pins Rust 1.85.1 in `pixi.lock`; it adds no Rust
dependency to the application build and does not provide a Rust source indexer.

## Set up and build

Install [Pixi](https://pixi.prefix.dev/latest/installation/) 0.83.0 or newer, then
run these commands from the repository root:

```sh
pixi install --locked
pixi run --locked build
pixi run --locked test
```

`--locked` checks that the manifest and the committed dependency lock agree;
it does not silently choose a new set of package versions. The initial install
requires access to conda-forge, and the first Python-enabled build downloads the
upstream `SourcetrailPythonIndexer` release from GitHub.

The environment includes Python 3.11, pytest 8, CMake 3, Ninja, GCC/G++ 12 with a
Linux sysroot, Boost, Qt 5, OpenGL development headers, and LLVM/Clang 11.1.
LLVM 11 is retained because the production C++ parser uses that API. All exact
package versions, builds, URLs, and package hashes are recorded in `pixi.lock`.
The external Python indexer is a bundled application with its own Python runtime;
the default environment's Python runs pytest and the test harness. A separate
`python-parser` environment provides Python 3.8 for the legacy Jedi/parso analyzer
to inspect. Its environment discovery cannot parse Python 3.10+ version strings.
The build task prepares this additional locked environment automatically, and
the tests explicitly pass its interpreter to the analyzer.

The build enables `BUILD_CXX_LANGUAGE_PACKAGE` and `BUILD_PYTHON_LANGUAGE_PACKAGE`,
and disables `BUILD_JAVA_LANGUAGE_PACKAGE`. Java source indexing is outside this
build; the separate `formal` environment uses Java only to run TLC.
The Pixi lock currently covers `linux-64` only; the original manual
Windows and macOS build instructions still describe those platforms.
The host must provide Linux 4.18 or newer and glibc 2.28 or newer, as recorded in
the lockfile. The older compiler sysroot does not lower these runtime requirements.

Outputs are placed under `build/pixi`:

| Output | Purpose |
| --- | --- |
| `app/Sourcetrail` | The application and its `index` command |
| `app/sourcetrail_indexer` | The C++ indexing worker |
| `test/Sourcetrail_test` | Existing and new Catch C++ tests |
| `test-results.xml` | CTest JUnit report from `pixi run test` |
| `Testing/Temporary/LastTest.log` | Detailed output from the latest CTest run |

CMake creates the resource links required by the executables. The Python indexer
is installed in `bin/app/data/python`, which is excluded from version control.
Forks without upstream version tags build with a numeric `0.0.0` fallback and
retain the Git commit identifier.

The default build uses two compile jobs to limit memory use. For a machine with
more available memory, configure once and invoke CMake directly:

```sh
pixi run configure
pixi run cmake --build build/pixi --parallel 4
```

## Run individual suites

Every named test task depends on the build, so it also works from a fresh checkout.

| Task | Coverage |
| --- | --- |
| `pixi run --locked test` | All ten CTest suites, including toy and standalone core contracts |
| `pixi run --locked test-contracts` | C++ refresh/source-group contracts and Python graph/verification contracts |
| `pixi run --locked test-toys` | Real C++/Python toy projects, authored facts, update/clean equivalence, negative controls |
| `pixi run -e portability --locked test-core` | Independent standard C++ core build and contracts |
| `pixi run -e portability --locked verify-portability` | Core build plus C++/Rust value-contract conformance and required mutant detection |
| `pixi run --locked test-legacy` | Existing Catch tests, excluding the newly tagged suites |
| `pixi run --locked test-cpp-regression` | Production C++ parser, symbol graph, source locations, and diagnostics |
| `pixi run --locked test-cpp-e2e` | Actual application, compilation database, persisted C++ index, and refresh |
| `pixi run --locked test-python-regression` | Actual bundled Python indexer and its SQLite output |
| `pixi run --locked test-python-e2e` | Actual application, Python project indexing, postprocessing, and refresh |

The new C++ regression cases cover overload resolution, preprocessor settings
that must not leak between parses, merging declarations with definitions while
retaining their source locations, and diagnostics that must not contaminate the
next parse. A focused refresh regression also checks the selection of incomplete
source files and source files that depend on incomplete headers. A subprocess
regression checks Unicode executable paths, arguments, and working directories.
Unicode trimming is checked independently so captured process output retains its
first non-ASCII character. The existing file-system suite also exercises traversal
past self-referencing symbolic links.

The C++ E2E cases create temporary multi-file projects with compilation databases
and paths containing spaces. They inspect the database produced by the actual
`Sourcetrail index` command, verify calls across translation units, check that an
unchanged refresh preserves the graph, remove stale renamed symbols, and repair
incomplete files using `--incomplete`.

The Python regression cases exercise function definitions, calls, inheritance,
same-named methods in different classes, UTF-8 source and paths, and persisted
syntax diagnostics. Python E2E cases exercise multi-file project indexing,
qualified-call postprocessing in both shallow and full indexing modes, source
modification, file deletion, stale graph cleanup, and stable results when indexing
unchanged input again.

These are command-line indexing E2E tests. They cover the path from source project
to the application and its index database; they do not automate GUI interactions.
They invoke real processes and inspect real databases. Missing executables,
timeouts, absent database schemas, and empty test selections fail the test run.

## Test isolation and troubleshooting

New tests write projects, settings, and databases to temporary directories. Linux
Sourcetrail explicitly looks up settings under `HOME/.config/sourcetrail`, so the
test helpers give only their child processes an isolated home directory. They do
not modify the invoking shell's home or the developer's Sourcetrail settings.
Qt uses `offscreen` for unattended runs. Incremental tests advance file mtimes
explicitly because the application records timestamps at second precision.

CTest sets the correct working directory for the original Catch suite and passes
the built application path to the new tests. For debugging without rebuilding:

```sh
pixi run ctest --test-dir build/pixi --output-on-failure --no-tests=error -R '^cpp-e2e$'
pixi run python -m pytest -c tests/python/pytest.ini tests/python -m regression -v
```

The Python helpers accept `SOURCETRAIL_BINARY`, `SOURCETRAIL_PYTHON_INDEXER`, and
`SOURCETRAIL_PYTHON_ENVIRONMENT` environment overrides. The last defaults to
`.pixi/envs/python-parser/bin/python` and can also point to an environment
directory. The C++ E2E helper also accepts `SOURCETRAIL_BINARY`. Use absolute
executable paths and retain their accompanying resource directories.

If CMake was previously configured with another compiler or dependency prefix,
use a fresh build directory before configuring with Pixi. Do not mix a previously
configured system toolchain with this environment. To update dependencies
deliberately, edit `pixi.toml`, run `pixi install`, then build and run the complete
test task before committing both the manifest and the regenerated lockfile.

The Python indexer bootstrap verifies a fixed SHA256 checksum and the executable's
version before installing the archive. Failed downloads or validation leave an
existing installation intact, and repeated builds reuse a verified installation.

GitHub Actions installs the committed lock, builds both language packages, and
runs the registered CTest suites, modern language adapter tests, documentation
checks, and bounded TLA+ verification. The CTest inventory is available with
`pixi run --locked ctest --test-dir build/pixi -N`.
Test logs, the JUnit report, model results, and model counterexamples are retained
as workflow artifacts, including on failure.

## Modern Python, C++ and Rust adapters

The separate `modern` environment pins Python 3.14, Clang 18.1.8 and Rust/Cargo 1.85.1.
`pixi run --locked -e modern test-modern-indexers` prepares the checksum-verified Rust engine,
builds the application, and runs engine, output-validation and real-application E2E cases.
It is also included in `pixi run --locked verify`. The previous Python 3.8 and Clang 11
paths remain available. See [modern indexers](architecture/modern-indexers.md) for project
creation, engine options, exact tested capabilities, and unsupported configurations.

Input observation tests and two additional portable C++ core programs are registered
in CTest. Four new normal/mutant TLA+ configurations cover content observations and
Python output acceptance; each negative control requires its named invariant violation.
