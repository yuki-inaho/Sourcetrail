"""Protect the model runner against false passes and unverified tools."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_models", ROOT / "script" / "verification" / "check_models.py"
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)

SUCCESS = """Model checking completed. No error has been found.
82,944 states generated, 69,120 distinct states found, 0 states left on queue.
"""
COUNTEREXAMPLE = """Error: Invariant SharedDependenciesPreserved is violated.
Error: The behavior up to this point is:
30 states generated, 30 distinct states found, 5 states left on queue.
"""


def test_success_requires_completed_nonempty_exploration():
    result = RUNNER.evaluate_result(0, SUCCESS, None)
    assert result["passed"]
    assert result["states"] == {"generated": 82944, "distinct": 69120, "pending": 0}


@pytest.mark.parametrize("returncode,output", [
    (1, SUCCESS),
    (0, ""),
    (0, SUCCESS.replace("69,120", "0")),
    (0, SUCCESS.replace("0 states left", "1 states left")),
    (0, SUCCESS.replace("Model checking completed. No error has been found.", "")),
])
def test_failed_or_incomplete_model_check_is_rejected(returncode, output):
    assert not RUNNER.evaluate_result(returncode, output, None)["passed"]


def test_negative_control_requires_the_specific_invariant_counterexample():
    assert RUNNER.evaluate_result(12, COUNTEREXAMPLE, "SharedDependenciesPreserved")["passed"]


@pytest.mark.parametrize("returncode,output", [
    (0, SUCCESS),
    (1, "Parse error in module RefreshPlan"),
    (12, COUNTEREXAMPLE.replace("SharedDependenciesPreserved", "TypeInvariant")),
    (12, COUNTEREXAMPLE.replace("The behavior up to this point is:", "")),
    (255, COUNTEREXAMPLE),
])
def test_negative_control_does_not_accept_arbitrary_failure(returncode, output):
    assert not RUNNER.evaluate_result(returncode, output, "SharedDependenciesPreserved")["passed"]


def test_corrupt_cached_jar_is_rejected_before_execution(tmp_path):
    jar = tmp_path / "tla2tools.jar"
    jar.write_bytes(b"unverified executable content")
    with pytest.raises(ValueError, match="checksum mismatch"):
        RUNNER.ensure_jar(jar, offline=True)
    assert jar.read_bytes() == b"unverified executable content"


def test_offline_mode_fails_when_tool_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing in offline mode"):
        RUNNER.ensure_jar(tmp_path / "missing.jar", offline=True)
