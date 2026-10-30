#!/usr/bin/env python3
"""Check contract traceability and the structure of source annotation reports.

This is a structural check, not evidence that a claim is true or that a review
covered every behavior. Historical source hashes are never compared with HEAD.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
DOC_DIRS = (
    "docs/architecture", "docs/adr", "docs/contracts", "docs/reports",
    ".agents/skills/annotate-contract-batch",
)
ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{3}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def without_fences(text: str) -> str:
    output = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            current = marker.group(1)
            if fence is None:
                fence = current
            elif current[0] == fence[0] and len(current) >= len(fence):
                fence = None
            continue
        if fence is None:
            output.append(line)
    return "\n".join(output)


def markdown_anchors(text: str) -> set[str]:
    anchors = set(re.findall(r'<a\s+(?:name|id)=["\']([^"\']+)["\']', text))
    seen: dict[str, int] = {}
    for match in re.finditer(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", without_fences(text), re.MULTILINE):
        title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", match.group(1))
        title = re.sub(r"<[^>]+>", "", title).replace("`", "").lower()
        slug = re.sub(r"[^\w\-\s]", "", title).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def markdown_targets(text: str) -> list[str]:
    text = re.sub(r"`+[^`]*`+", "", without_fences(text))
    targets = []
    for match in re.finditer(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)", text):
        targets.append(match.group(1) or match.group(2))
    for match in re.finditer(r"^\s{0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))", text, re.MULTILINE):
        targets.append(match.group(1) or match.group(2))
    return targets


def repo_path(root: Path, value: Any, label: str, errors: list[str], *, exists: bool = True) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        errors.append(f"{label}: require a nonempty repository-relative path")
        return None
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        errors.append(f"{label}: path escapes repository: {value}")
        return None
    if exists and not path.exists():
        errors.append(f"{label}: missing path: {value}")
        return None
    return path


def read_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{path}: cannot read JSON: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path}: expected a JSON object")
        return None
    return value


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_literal_reference(root: Path, reference: Any, field: str, label: str, errors: list[str]) -> None:
    if not isinstance(reference, dict):
        errors.append(f"{label}: expected an object")
        return
    path = repo_path(root, reference.get("path"), label, errors)
    anchor = reference.get(field)
    if not nonempty_text(anchor):
        errors.append(f"{label}: {field} must be a nonempty literal string")
    elif path is not None:
        if not path.is_file():
            errors.append(f"{label}: literal reference must name a file")
        elif anchor not in path.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"{label}: literal {field} not found: {anchor!r}")


def check_catalog(root: Path, errors: list[str]) -> set[str]:
    path = root / "docs/contracts/catalog.json"
    catalog = read_json(path, errors)
    if catalog is None:
        return set()
    if catalog.get("schema_version") != 1:
        errors.append("catalog: unsupported schema_version")
    contracts = catalog.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        errors.append("catalog: contracts must be a nonempty list")
        return set()
    ids: set[str] = set()
    for index, contract in enumerate(contracts):
        label = f"catalog contracts[{index}]"
        if not isinstance(contract, dict):
            errors.append(f"{label}: expected an object")
            continue
        identifier = contract.get("id")
        if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
            errors.append(f"{label}: invalid contract ID")
        elif identifier in ids:
            errors.append(f"{label}: duplicate contract ID: {identifier}")
        else:
            ids.add(identifier)
            label = identifier
        for field in ("title", "scope"):
            if not nonempty_text(contract.get(field)):
                errors.append(f"{label}: {field} must be nonempty")
        status = contract.get("status")
        if status not in {"enforced", "characterized", "planned"}:
            errors.append(f"{label}: invalid status")
        for field, anchor in (("sources", "symbol"), ("verification", "anchor")):
            references = contract.get(field)
            if not isinstance(references, list):
                errors.append(f"{label}: {field} must be a list")
                continue
            if status != "planned" and not references:
                errors.append(f"{label}: non-planned contract needs {field} evidence")
            for reference in references:
                check_literal_reference(root, reference, anchor, f"{label} {field}", errors)
        documents = contract.get("docs")
        if not isinstance(documents, list) or not documents:
            errors.append(f"{label}: docs must be a nonempty list")
        else:
            for document in documents:
                repo_path(root, document, f"{label} docs", errors)
        limitations = contract.get("limitations")
        if not isinstance(limitations, list) or not all(nonempty_text(item) for item in limitations):
            errors.append(f"{label}: limitations must be a list of nonempty strings")
    return ids


def check_markdown(root: Path, path: Path, contract_ids: set[str], errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for target in markdown_targets(text):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        destination = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if not destination.is_relative_to(root):
            errors.append(f"{path.relative_to(root)}: local link escapes repository: {target}")
        elif not destination.exists():
            errors.append(f"{path.relative_to(root)}: broken local link: {target}")
        elif parsed.fragment and destination.suffix.lower() == ".md":
            if unquote(parsed.fragment) not in markdown_anchors(destination.read_text(encoding="utf-8")):
                errors.append(f"{path.relative_to(root)}: missing heading anchor: {target}")
    prefixes = {identifier.rsplit("-", 1)[0] for identifier in contract_ids}
    for identifier in re.findall(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{3}\b", without_fences(text)):
        if identifier.rsplit("-", 1)[0] in prefixes and identifier not in contract_ids:
            errors.append(f"{path.relative_to(root)}: unknown contract ID: {identifier}")


def check_profiles(root: Path, contract_ids: set[str], errors: list[str]) -> int:
    profiles = read_json(root / "docs/contracts/language-profiles.json", errors)
    if profiles is None:
        return 0
    if profiles.get("schema_version") != 1:
        errors.append("language profiles: unsupported schema_version")
    entries = profiles.get("profiles")
    if not isinstance(entries, list) or not entries:
        errors.append("language profiles: profiles must be a nonempty list")
        return 0
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("language profiles: entry must be an object")
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier):
            errors.append("language profiles: invalid profile ID")
        elif identifier in seen:
            errors.append(f"language profiles: duplicate profile ID: {identifier}")
        else:
            seen.add(identifier)
        required = entry.get("requires_contracts")
        if not isinstance(required, list) or not required:
            errors.append(f"language profile {identifier}: requires_contracts must be a nonempty list")
        else:
            for contract in required:
                if not isinstance(contract, str) or contract not in contract_ids:
                    errors.append(f"language profile {identifier}: unknown contract ID: {contract}")
    return len(seen)


def check_report(root: Path, path: Path, contract_ids: set[str], errors: list[str]) -> None:
    report = read_json(path, errors)
    if report is None:
        return
    label = str(path.relative_to(root))
    if report.get("schema_version") != 1:
        errors.append(f"{label}: unsupported schema_version")
    if report.get("kind") != "source":
        errors.append(f"{label}: this workflow accepts source reports only; do not label absent images")
    if report.get("batch_id") != path.parent.name:
        errors.append(f"{label}: batch_id must match its directory")
    try:
        recorded_date = date.fromisoformat(report.get("created_on", ""))
        if recorded_date.isoformat() != path.parent.parent.name:
            errors.append(f"{label}: date must match its directory")
    except (ValueError, TypeError):
        errors.append(f"{label}: invalid created_on date")
    revision = report.get("source_revision")
    if not isinstance(revision, dict):
        errors.append(f"{label}: source_revision must be an object")
        revision = {}
    base = revision.get("base_commit")
    base_available = False
    if not isinstance(base, str) or not COMMIT_PATTERN.fullmatch(base):
        errors.append(f"{label}: base_commit must be a full 40-character commit SHA")
    elif (root / ".git").exists():
        resolved = subprocess.run(
            ["git", "cat-file", "-t", base], cwd=root, text=True, capture_output=True, check=False,
        )
        if resolved.returncode or resolved.stdout.strip() != "commit":
            errors.append(f"{label}: recorded base_commit is not an available commit; fetch its history")
        else:
            base_available = True
    mode = revision.get("mode")
    if mode not in {"base-commit", "working-tree"}:
        errors.append(f"{label}: source revision mode must be base-commit or working-tree")
    if not nonempty_text(revision.get("note")):
        errors.append(f"{label}: explain what the recorded base commit and snapshot mean")
    report_file = report.get("report")
    if report_file != "report.md":
        errors.append(f"{label}: report must be report.md")
    report_path = path.parent / "report.md"
    if not report_path.is_file():
        errors.append(f"{label}: missing report.md")
        report_text = ""
    else:
        report_text = report_path.read_text(encoding="utf-8")
    units = report.get("units")
    if not isinstance(units, list) or not 1 <= len(units) <= 10:
        errors.append(f"{label}: units must contain 1 to 10 source annotations")
        units = []
    unit_ids = set()
    for unit in units:
        if not isinstance(unit, dict):
            errors.append(f"{label}: annotation must be an object")
            continue
        identifier = unit.get("id")
        unit_label = f"{label} {identifier}"
        if not isinstance(identifier, str) or not re.fullmatch(r"ANN-\d{3}", identifier):
            errors.append(f"{unit_label}: invalid annotation ID")
        elif identifier in unit_ids:
            errors.append(f"{unit_label}: duplicate annotation ID")
        else:
            unit_ids.add(identifier)
            if identifier not in report_text:
                errors.append(f"{unit_label}: annotation is missing from report.md")
        # A historical path can be renamed or removed later. Its captured hash is
        # evidence for that snapshot, not a requirement on the current checkout.
        repo_path(root, unit.get("path"), unit_label, errors, exists=False)
        if not isinstance(unit.get("sha256"), str) or not SHA256_PATTERN.fullmatch(unit["sha256"]):
            errors.append(f"{unit_label}: invalid recorded source SHA-256")
        for field in ("symbol", "excerpt", "observation", "uncertainty", "next_action"):
            if not nonempty_text(unit.get(field)):
                errors.append(f"{unit_label}: {field} must be nonempty")
        if mode == "base-commit" and base_available and isinstance(unit.get("path"), str):
            recorded = subprocess.run(
                ["git", "show", f"{base}:{unit['path']}"], cwd=root, capture_output=True, check=False,
            )
            if recorded.returncode:
                errors.append(f"{unit_label}: source does not exist in the recorded base commit")
            elif hashlib.sha256(recorded.stdout).hexdigest() != unit.get("sha256"):
                errors.append(f"{unit_label}: source hash does not match the recorded base commit")
            else:
                content = recorded.stdout.decode("utf-8", errors="replace")
                for field in ("symbol", "excerpt"):
                    if nonempty_text(unit.get(field)) and unit[field] not in content:
                        errors.append(f"{unit_label}: {field} not found in the recorded base commit")
        contracts = unit.get("contracts")
        if not isinstance(contracts, list) or not contracts:
            errors.append(f"{unit_label}: contracts must be a nonempty list")
        else:
            for identifier in contracts:
                if not isinstance(identifier, str) or identifier not in contract_ids:
                    errors.append(f"{unit_label}: unknown contract ID: {identifier}")
        if unit.get("finding_type") not in {"observed", "inferred", "unresolved"}:
            errors.append(f"{unit_label}: invalid finding_type")
    evidence = report.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{label}: evidence must be a nonempty list")
    else:
        for item in evidence:
            if not isinstance(item, dict):
                errors.append(f"{label}: evidence entry must be an object")
                continue
            repo_path(root, item.get("path"), f"{label} evidence", errors)
            if not nonempty_text(item.get("description")):
                errors.append(f"{label}: evidence description must be nonempty")
    review = report.get("review")
    if not isinstance(review, dict) or review.get("status") not in {"pending", "completed"}:
        errors.append(f"{label}: review status must be pending or completed")
    elif review["status"] == "completed":
        repo_path(root, review.get("evidence_path"), f"{label} completed review", errors)


def validate(root: Path) -> tuple[list[str], dict[str, int]]:
    root = root.resolve()
    errors: list[str] = []
    contract_ids = check_catalog(root, errors)
    profile_count = check_profiles(root, contract_ids, errors)
    markdown = {root / "docs/README.md"}
    for directory in DOC_DIRS:
        markdown.update((root / directory).rglob("*.md"))
    for path in sorted(markdown):
        if not path.is_file():
            errors.append(f"{path.relative_to(root)}: missing documentation entry point")
        else:
            check_markdown(root, path, contract_ids, errors)
    manifests = sorted((root / "docs/reports").glob("????-??-??/*/manifest.json"))
    for manifest in manifests:
        check_report(root, manifest, contract_ids, errors)
    return errors, {
        "markdown_files": len(markdown), "contracts": len(contract_ids),
        "language_profiles": profile_count, "reports": len(manifests),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors, counts = validate(args.root)
    for error in errors:
        print(f"ERROR: {error}")
    print(json.dumps({"passed": not errors, **counts, "error_count": len(errors)}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
