#!/usr/bin/env python3
"""Compare the production C++ value core and a std-only Rust reference port.

The ASCII refresh-sets-v1 transport uses six input masks and four output masks.
This checks a policy boundary; it neither implements Rust indexing nor proves arbitrary
input sizes, native path semantics, or Windows/macOS application compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
INPUT_ORDER = (
    "sources", "unchanged", "changed", "referencing_changed",
    "referenced_static", "referenced_affected",
)
OUTPUT_ORDER = ("affected", "retained", "clear", "index")
MAX_MASK = (1 << 64) - 1
BOUNDED_CASES = 64 * 8 * 8 * 8


class VerificationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity_mask(values: object, label: str) -> int:
    if not isinstance(values, list) or any(type(value) is not int for value in values):
        raise VerificationError(f"{label}: expected an integer identity list")
    if any(value < 0 or value >= 64 for value in values):
        raise VerificationError(f"{label}: identities must be in 0..63")
    if values != sorted(set(values)):
        raise VerificationError(f"{label}: identity lists must be sorted and unique")
    return sum(1 << value for value in values)


def load_vectors(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VerificationError("fixed-vector document must be an object")
    if (type(document.get("schema_version")) is not int or
            document.get("schema_version") != 1 or
            document.get("profile") != "refresh-sets-v1" or
            document.get("identity_bits") != 64 or
            document.get("input_order") != list(INPUT_ORDER) or
            document.get("output_order") != list(OUTPUT_ORDER)):
        raise VerificationError("unsupported fixed-vector schema or transport profile")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise VerificationError("fixed-vector suite must not be empty")
    result = []
    identifiers: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise VerificationError("fixed-vector cases must be objects")
        identifier = case.get("id")
        if (not isinstance(identifier, str) or
                re.fullmatch(r"[a-z][a-z0-9-]*", identifier) is None or
                identifier in identifiers):
            raise VerificationError("fixed-vector identifiers must be valid and unique")
        identifiers.add(identifier)
        if not isinstance(case.get("reason"), str) or not case["reason"].strip():
            raise VerificationError(f"{identifier}: a design reason is required")
        inputs, expected = case.get("input"), case.get("expected")
        if not isinstance(inputs, dict) or set(inputs) != set(INPUT_ORDER):
            raise VerificationError(f"{identifier}: incomplete input fields")
        if not isinstance(expected, dict) or set(expected) != set(OUTPUT_ORDER):
            raise VerificationError(f"{identifier}: incomplete expected fields")
        result.append({
            "id": identifier,
            "input": tuple(identity_mask(inputs[key], f"{identifier}/{key}") for key in INPUT_ORDER),
            "expected": tuple(identity_mask(expected[key], f"{identifier}/{key}") for key in OUTPUT_ORDER),
        })
    return result


def bounded_vectors() -> list[dict]:
    """Independent Boolean/Warshall oracle, rather than the production set algorithm."""
    possible_edges = ((0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1))
    cases = []
    for graph in range(64):
        reaches = [[False] * 3 for _ in range(3)]
        for bit, (source, target) in enumerate(possible_edges):
            reaches[source][target] = bool(graph & (1 << bit))
        for via in range(3):
            for source in range(3):
                for target in range(3):
                    reaches[source][target] |= reaches[source][via] and reaches[via][target]
        for sources in range(8):
            for changed in range(8):
                reverse = sum(1 << file for file in range(3) if any(
                    changed & (1 << target) and reaches[file][target] for target in range(3)))
                affected = [bool(changed & (1 << file) or reverse & (1 << file)) for file in range(3)]
                retained = [bool(sources & (1 << file)) and not affected[file] for file in range(3)]
                static_use = [any(retained[owner] and reaches[owner][file] for owner in range(3))
                              for file in range(3)]
                affected_use = [any(affected[owner] and reaches[owner][file] for owner in range(3))
                                for file in range(3)]
                affected_mask = sum(1 << file for file in range(3) if affected[file])
                retained_mask = sum(1 << file for file in range(3) if retained[file])
                static_mask = sum(1 << file for file in range(3) if static_use[file])
                dynamic_mask = sum(1 << file for file in range(3) if affected_use[file])
                clear = [affected[file] or (affected_use[file] and not static_use[file]
                         and not bool(sources & (1 << file))) for file in range(3)]
                clear_mask = sum(1 << file for file in range(3) if clear[file])
                for unchanged in range(8):
                    index_mask = sum(1 << file for file in range(3)
                                     if sources & (1 << file)
                                     and (clear[file] or not unchanged & (1 << file)))
                    cases.append({
                        "id": f"bounded/{graph}/{sources}/{changed}/{unchanged}",
                        "input": (sources, unchanged, changed, reverse, static_mask, dynamic_mask),
                        "expected": (affected_mask, retained_mask, clear_mask, index_mask),
                    })
    if len(cases) != BOUNDED_CASES:
        raise VerificationError(f"bounded oracle generated {len(cases)}, expected {BOUNDED_CASES}")
    return cases


def parse_results(output: str, expected_count: int) -> list[tuple[int, ...]]:
    if not output.isascii():
        raise VerificationError("driver output must be ASCII")
    lines = output.splitlines()
    if expected_count <= 0 or len(lines) != expected_count:
        raise VerificationError(f"driver returned {len(lines)} rows; expected {expected_count}")
    results = []
    for number, line in enumerate(lines, 1):
        tokens = line.split()
        if len(tokens) != 4 or any(re.fullmatch(r"[0-9]+", token) is None for token in tokens):
            raise VerificationError(f"driver row {number}: expected four unsigned decimal masks")
        values = tuple(int(token) for token in tokens)
        if any(value > MAX_MASK for value in values):
            raise VerificationError(f"driver row {number}: mask exceeds unsigned 64-bit range")
        results.append(values)
    return results


def mismatches(cases: list[dict], results: list[tuple[int, ...]]) -> list[str]:
    if not cases or len(cases) != len(results):
        raise VerificationError("cannot compare empty or unequal result lists")
    return [case["id"] for case, actual in zip(cases, results) if actual != case["expected"]]


def executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise VerificationError(f"required executable is unavailable: {name}")
    return path


def run(command: list[str], *, input_text: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    result = subprocess.run(command, input=input_text, capture_output=True, text=True,
                            encoding="utf-8", errors="strict", timeout=timeout, cwd=ROOT)
    if result.returncode != 0:
        raise VerificationError(
            f"command failed ({result.returncode}): {command!r}\n{result.stdout}\n{result.stderr}")
    return result


def execute_cases(command: list[str], cases: list[dict]) -> tuple[list[tuple[int, ...]], str]:
    payload = "".join(" ".join(map(str, case["input"])) + "\n" for case in cases)
    result = run(command, input_text=payload)
    return parse_results(result.stdout, len(cases)), result.stdout


def verify(cpp_driver: Path, output: Path) -> dict:
    started = time.monotonic()
    vectors_path = ROOT / "tests/portability/refresh_vectors.json"
    rust_source = ROOT / "tests/portability/refresh_reference.rs"
    fixed = load_vectors(vectors_path)
    bounded = bounded_vectors()
    cases = fixed + bounded
    if not cpp_driver.is_file() or not os.access(cpp_driver, os.X_OK):
        raise VerificationError(f"required C++ driver is missing or not executable: {cpp_driver}")
    rustc = executable("rustc")
    linker = executable(os.environ.get("CC", "cc"))
    cxx = executable(os.environ.get("CXX", "c++"))
    rust_driver = output / ("refresh-reference.exe" if os.name == "nt" else "refresh-reference")
    compile_command = [rustc, "--edition=2021", "-C", "opt-level=2", "-C", f"linker={linker}",
                       str(rust_source), "-o", str(rust_driver)]
    compilation = run(compile_command)
    (output / "rust-build.log").write_text(compilation.stdout + compilation.stderr, encoding="utf-8")
    implementations = {}
    for name, driver in (("cpp", cpp_driver), ("rust", rust_driver)):
        results, text = execute_cases([str(driver)], cases)
        (output / f"{name}-results.txt").write_text(text, encoding="ascii")
        wrong = mismatches(cases, results)
        if wrong:
            raise VerificationError(f"{name}: {len(wrong)} mismatches, first {wrong[:5]}")
        implementations[name] = {
            "status": "passed", "cases": len(cases), "mismatches": 0,
            "binary_sha256": sha256(driver),
            "result_sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
        }
    mutant_results, mutant_text = execute_cases(
        [str(rust_driver), "--omit-shared-protection"], fixed)
    rejected_cases = mismatches(fixed, mutant_results)
    if "shared-and-private" not in rejected_cases:
        raise VerificationError("negative control failed to expose missing shared dependency protection")
    (output / "negative-control-results.txt").write_text(mutant_text, encoding="ascii")
    versions = {
        "python": sys.version.splitlines()[0],
        "rustc": run([rustc, "--version"]).stdout.strip(),
        "cxx": run([cxx, "--version"]).stdout.splitlines()[0],
        "linker_driver": run([linker, "--version"]).stdout.splitlines()[0],
    }
    source_paths = (
        "src/lib_core/RefreshPlanner.h", "tests/portability/refresh_driver.cpp",
        "tests/portability/refresh_reference.rs", "tests/portability/refresh_vectors.json",
        "script/verification/check_portability.py",
    )
    return {
        "schema_version": 1, "profile": "refresh-sets-v1", "status": "passed",
        "versions": versions, "compile_command": compile_command,
        "source_sha256": {path: sha256(ROOT / path) for path in source_paths},
        "fixed_cases": len(fixed), "fixed_case_ids": [case["id"] for case in fixed],
        "bounded_cases": len(bounded),
        "bounded_domain": {"identities": 3, "directed_nonself_graphs": 64,
                           "source_subsets": 8, "changed_subsets": 8, "unchanged_subsets": 8,
                           "overlapping_changed_unchanged_included": True},
        "implementations": implementations,
        "negative_control": {"status": "expected-mismatch", "cases": len(fixed),
                             "rejected_case_ids": rejected_cases,
                             "required_rejected_case": "shared-and-private"},
        "duration_seconds": round(time.monotonic() - started, 3),
        "scope": "C++ production value core / Rust reference policy; no Rust indexing or OS application proof",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp-driver", type=Path, default=ROOT / "build/core/core-refresh-driver")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/portability")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        summary = verify(args.cpp_driver.resolve(), output)
        exit_code = 0
    except (VerificationError, OSError, ValueError, subprocess.SubprocessError) as error:
        summary = {"schema_version": 1, "profile": "refresh-sets-v1", "status": "failed", "error": str(error)}
        exit_code = 1
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
