"""All integration tests use built binaries and isolated writable projects."""

from pathlib import Path
import os
import shutil
import xml.etree.ElementTree as ET

import pytest

from support import PythonIndexer, SourcetrailProject


REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def required_executable(variable: str, default: Path) -> Path:
    executable = Path(os.environ.get(variable, str(default))).expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        pytest.fail(
            f"Required executable is missing or not executable: {executable}. "
            f"Run `pixi run build` first, or set {variable} to a built executable.",
            pytrace=False,
        )
    return executable


@pytest.fixture
def process_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    test_home = tmp_path / "isolated-home"
    test_home.mkdir()
    settings_directory = test_home / ".config/sourcetrail"
    settings_directory.mkdir(parents=True)
    (settings_directory / "ApplicationSettings.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<config><indexing><indexer_thread_count>1</indexer_thread_count>"
        "</indexing><version>8</version></config>\n",
        encoding="utf-8",
    )
    # The Linux application explicitly reads HOME instead of XDG_CONFIG_HOME.
    # Only child processes receive this environment; user settings stay intact.
    environment.update(
        HOME=str(test_home), QT_QPA_PLATFORM="offscreen",
        SOURCETRAIL_VIA_SCRIPT="1",
    )
    return environment


@pytest.fixture
def python_environment() -> Path:
    # The shipped Jedi 0.17/parso 0.7 parser requires a Python 3.8 environment.
    environment = Path(os.environ.get(
        "SOURCETRAIL_PYTHON_ENVIRONMENT",
        str(REPOSITORY / ".pixi/envs/python-parser/bin/python"),
    )).expanduser().resolve()
    if environment.is_dir():
        environment = environment / "bin/python"
    if not environment.is_file() or not os.access(environment, os.X_OK):
        pytest.fail(
            f"Python parser environment is missing: {environment}. "
            "Run `pixi install --locked --environment python-parser`, or set "
            "SOURCETRAIL_PYTHON_ENVIRONMENT to a compatible Python interpreter.",
            pytrace=False,
        )
    return environment


@pytest.fixture
def python_indexer(tmp_path: Path, process_environment: dict[str, str],
                   python_environment: Path) -> PythonIndexer:
    executable = required_executable(
        "SOURCETRAIL_PYTHON_INDEXER",
        REPOSITORY / "bin/app/data/python/SourcetrailPythonIndexer",
    )
    work_directory = tmp_path / "python source 日本語 with spaces"
    work_directory.mkdir()
    return PythonIndexer(executable, work_directory, process_environment, python_environment)


@pytest.fixture
def python_project(tmp_path: Path, process_environment: dict[str, str],
                   python_environment: Path) -> SourcetrailProject:
    executable = required_executable(
        "SOURCETRAIL_BINARY", REPOSITORY / "build/pixi/app/Sourcetrail",
    )
    project_directory = tmp_path / "python project 日本語 with spaces"
    shutil.copytree(
        FIXTURES / "project", project_directory,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    project_file = project_directory / "python.srctrlprj"
    project_settings = ET.parse(project_file)
    source_groups = project_settings.find("source_groups")
    assert source_groups is not None and len(source_groups) == 1
    ET.SubElement(source_groups[0], "python_environment_path").text = str(python_environment)
    project_settings.write(project_file, encoding="utf-8", xml_declaration=True)
    return SourcetrailProject(
        executable, project_file, process_environment,
    )
