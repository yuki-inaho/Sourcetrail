#!/usr/bin/env python3
"""Run the bounded TLA+ contract checks and required negative controls.

No third-party Python packages are required. The official TLC JAR is downloaded
only when absent and is always checked against a pinned SHA-256 before execution.
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
import tempfile
import time
from typing import Any
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "docs" / "contracts" / "formal"
TLC_VERSION = "1.7.4"
TLC_URL = f"https://github.com/tlaplus/tlaplus/releases/download/v{TLC_VERSION}/tla2tools.jar"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
CASES = (
    ("refresh-mixed", "RefreshPlan.tla", "RefreshPlan.cfg", None),
    ("refresh-single-relation", "RefreshPlan.tla", "RefreshPlanSingleRelation.cfg", None),
    ("refresh-negative-control", "RefreshPlan.tla", "RefreshPlanMutant.cfg", "SharedDependenciesPreserved"),
    ("external-indexing", "ExternalIndexing.tla", "ExternalIndexing.cfg", None),
    ("external-indexing-negative-control", "ExternalIndexing.tla", "ExternalIndexingMutant.cfg", "NoPublicationAfterFailure"),
    ("source-observation", "SourceObservation.tla", "SourceObservation.cfg", None),
    ("source-observation-negative-control", "SourceObservation.tla", "SourceObservationMutant.cfg", "ContentChangesDetected"),
    ("python-output-validation", "PythonOutputValidation.tla", "PythonOutputValidation.cfg", None),
    ("python-output-negative-control", "PythonOutputValidation.tla", "PythonOutputValidationMutant.cfg", "NoPublicationAfterInvalidOutput"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_jar(path: Path, *, offline: bool) -> None:
    """Install a verified release atomically; reject corrupt existing caches."""
    if path.exists():
        if sha256(path) != TLC_SHA256:
            raise ValueError(f"TLC JAR checksum mismatch: {path}; remove it and retry")
        return
    if offline:
        raise FileNotFoundError(f"Pinned TLC JAR is missing in offline mode: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".download", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            request = urllib.request.Request(TLC_URL, headers={"User-Agent": "Sourcetrail-contract-check"})
            with urllib.request.urlopen(request, timeout=60) as response:
                shutil.copyfileobj(response, stream)
            stream.close()
            if sha256(temporary) != TLC_SHA256:
                raise ValueError("Downloaded TLC JAR does not match the pinned SHA-256")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def evaluate_result(returncode: int, output: str, expected_violation: str | None) -> dict[str, Any]:
    """Require positive completion or the exact intended counterexample."""
    matches = list(re.finditer(
        r"([\d,]+) states generated, ([\d,]+) distinct states found, ([\d,]+) states left on queue\.",
        output,
    ))
    counts = None
    if matches:
        counts = dict(zip(
            ("generated", "distinct", "pending"),
            (int(value.replace(",", "")) for value in matches[-1].groups()),
        ))
    violation = re.search(r"Invariant (\w+) is violated\.", output)
    actual_violation = violation.group(1) if violation else None
    if expected_violation is None:
        passed = (
            returncode == 0
            and "Model checking completed. No error has been found." in output
            and counts is not None
            and counts["distinct"] > 0
            and counts["pending"] == 0
        )
    else:
        # A parser error, JVM failure, timeout, or wrong invariant is not a pass.
        passed = (
            returncode == 12
            and actual_violation == expected_violation
            and "The behavior up to this point is:" in output
            and counts is not None
            and counts["distinct"] > 0
        )
    return {
        "passed": passed,
        "returncode": returncode,
        "expected_violation": expected_violation,
        "actual_violation": actual_violation,
        "states": counts,
    }


def run_case(java: str, jar: Path, output_dir: Path, timeout: int,
             name: str, module: str, config: str,
             expected_violation: str | None) -> dict[str, Any]:
    log_path = output_dir / f"{name}.log"
    # Each run owns its temporary state directory. Do not delete other checks' data.
    with tempfile.TemporaryDirectory(prefix=f"{name}-", dir=output_dir) as state_dir:
        command = [
            java, "-XX:+UseParallelGC", "-Xmx1024m", "-jar", str(jar),
            "-workers", "1", "-fp", "0", "-seed", "1",
            "-metadir", state_dir, "-config", config, module,
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command, cwd=MODEL_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
            )
            output = completed.stdout
            result = evaluate_result(completed.returncode, output, expected_violation)
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or b""
            output = partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else partial
            output += f"\nRunner timeout after {timeout} seconds.\n"
            result = {"passed": False, "returncode": None, "error": "timeout"}
        log_path.write_text(output, encoding="utf-8")
        result.update({
            "name": name,
            "module": module,
            "config": config,
            "command": command,
            "seconds": round(time.monotonic() - started, 3),
            "log": str(log_path.relative_to(output_dir)),
        })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build" / "formal")
    parser.add_argument("--jar", type=Path, help="Use this JAR only if it has the pinned SHA-256")
    parser.add_argument("--java", default="java", help="Java executable; Java 11 or later required")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per configuration in seconds")
    parser.add_argument("--offline", action="store_true", help="Fail if the pinned JAR is absent")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    jar = (args.jar or output_dir / f"tla2tools-{TLC_VERSION}.jar").resolve()
    summary: dict[str, Any] = {
        "schema_version": 1,
        "scope": "bounded model safety/refinement; not a proof of C++ or whole-application equivalence",
        "tlc": {"release": TLC_VERSION, "url": TLC_URL, "sha256": TLC_SHA256},
        "model_sha256": {
            path.name: sha256(path)
            for path in sorted(MODEL_DIR.iterdir()) if path.suffix in {".tla", ".cfg"}
        },
        "results": [],
        "passed": False,
    }
    try:
        ensure_jar(jar, offline=args.offline)
        java = shutil.which(args.java)
        if java is None:
            raise FileNotFoundError(f"Java executable not found: {args.java}")
        version = subprocess.run(
            [java, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", timeout=30, check=True,
        ).stdout.strip()
        summary["java"] = version
        for case in CASES:
            print(f"Checking {case[0]} ...", flush=True)
            result = run_case(java, jar, output_dir, args.timeout, *case)
            summary["results"].append(result)
            print(f"  {'PASS' if result['passed'] else 'FAIL'}: {result.get('states')}", flush=True)
        summary["passed"] = all(result["passed"] for result in summary["results"])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        summary["error"] = str(error)
        print(f"Model verification failed: {error}", file=sys.stderr)
    finally:
        summary_path = output_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {summary_path}", flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
