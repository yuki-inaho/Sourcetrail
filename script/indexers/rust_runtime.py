"""Install the pinned rust-analyzer and matching standard-library sources.

The compiler and Cargo are supplied by the locked Pixi ``modern`` environment.
Downloads are verified before an existing runtime can be replaced. Indexing
itself never downloads an engine; preparation is an explicit build task.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


ANALYZER_VERSION = "0.3.2328-standalone (81ff38f53b 2025-03-02)"
ANALYZER_URL = (
    "https://github.com/rust-lang/rust-analyzer/releases/download/2025-03-03/"
    "rust-analyzer-x86_64-unknown-linux-gnu.gz"
)
ANALYZER_ARCHIVE_SHA256 = "6cf40211f9755c63ac2f8f5fbeb4370d124aae7b1b082d501669b83e607762be"
ANALYZER_SHA256 = "d8bad3d2b4dc2d500ddbbe3842ab001b4f1ec353719164897b00a7f823e9a8ce"
RUST_VERSION = "1.85.1"
SOURCE_URL = "https://static.rust-lang.org/dist/rust-src-1.85.1.tar.xz"
SOURCE_SHA256 = "b5a5539009d477a07c2535aefc39cd69ad526a74eab65886a26e2c3021020827"
DEFAULT_DESTINATION = Path(__file__).resolve().parents[2] / "build/modern-runtimes/rust"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, path: Path, expected: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Sourcetrail-modern-indexers/1"})
    with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)
    if _sha256(path) != expected:
        raise RuntimeError(f"Rust runtime checksum mismatch: {url}")


def prepare(destination: Path = DEFAULT_DESTINATION) -> dict[str, str]:
    """Return installed paths, preserving a valid prior installation on failure."""
    destination = destination.resolve()
    analyzer = destination / "rust-analyzer"
    sources = destination / "library"
    manifest = destination / "runtime.json"
    expected_manifest = {
        "rust_analyzer_version": ANALYZER_VERSION,
        "rust_analyzer_sha256": ANALYZER_SHA256,
        "rust_src_version": RUST_VERSION,
        "rust_src_archive_sha256": SOURCE_SHA256,
        "standard_library_dependencies": "cargo-lock-linux-1",
    }
    cargo_home = destination / "cargo-home"
    if analyzer.is_file() and manifest.is_file() and (sources / "core/src/lib.rs").is_file() and (cargo_home / "registry").is_dir():
        try:
            current_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current_manifest = None
        if current_manifest == expected_manifest:
            if _sha256(analyzer) == ANALYZER_SHA256:
                return {"rust_analyzer": str(analyzer), "rust_src": str(sources), "cargo_home": str(cargo_home)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rust-runtime-", dir=destination.parent) as scratch:
        temporary = Path(scratch)
        archive = temporary / "rust-analyzer.gz"
        _download(ANALYZER_URL, archive, ANALYZER_ARCHIVE_SHA256)
        candidate = temporary / "runtime"
        candidate.mkdir()
        with gzip.open(archive, "rb") as source, (candidate / "rust-analyzer").open("wb") as output:
            shutil.copyfileobj(source, output)
        if _sha256(candidate / "rust-analyzer") != ANALYZER_SHA256:
            raise RuntimeError("Decompressed rust-analyzer checksum mismatch")
        (candidate / "rust-analyzer").chmod(0o755)
        source_archive = temporary / "rust-src.tar.xz"
        _download(SOURCE_URL, source_archive, SOURCE_SHA256)
        with tarfile.open(source_archive, "r:xz") as source:
            source.extractall(temporary / "source", filter="data")
        library = temporary / "source/rust-src-1.85.1/rust-src/lib/rustlib/src/rust/library"
        if not (library / "core/src/lib.rs").is_file():
            raise RuntimeError("Pinned Rust source archive has an unexpected layout")
        shutil.move(str(library), candidate / "library")
        cargo = shutil.which("cargo")
        if cargo is None:
            raise RuntimeError("Prepare Rust through the locked Pixi modern environment (Cargo is required)")
        environment = os.environ.copy()
        environment["CARGO_HOME"] = str(candidate / "cargo-home")
        # Rust's own std manifests use Cargo's public-dependency feature. The
        # pinned analyzer applies the same metadata-only bootstrap internally.
        # This setting is not inherited by project compilation or indexing.
        environment["RUSTC_BOOTSTRAP"] = "1"
        environment["CARGO_NET_OFFLINE"] = "false"
        result = subprocess.run(
            [cargo, "fetch", "--locked", "--manifest-path", str(candidate / "library/Cargo.toml"),
             "--target", "x86_64-unknown-linux-gnu"],
            env=environment, capture_output=True, text=True, timeout=300,
        )
        if result.returncode:
            raise RuntimeError(f"Cannot prepare locked standard-library dependencies: {result.stderr[-8000:]}")
        (candidate / "runtime.json").write_text(
            json.dumps(expected_manifest, indent=2) + "\n", encoding="utf-8"
        )
        # All checks precede replacement. Rename the previous tree so a failed
        # installation can restore it without removing a known working engine.
        backup = temporary / "previous"
        had_previous = destination.exists()
        if had_previous:
            destination.rename(backup)
        try:
            candidate.rename(destination)
        except BaseException:
            if had_previous:
                backup.rename(destination)
            raise
    return {"rust_analyzer": str(analyzer), "rust_src": str(sources), "cargo_home": str(cargo_home)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    arguments = parser.parse_args()
    print(json.dumps(prepare(arguments.destination), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
