"""Verify acquired Sprint 1 source files against the tracked manifest."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, TextIO

REQUIRED_MANIFEST_COLUMNS = {
    "source_id",
    "role",
    "canonical_url",
    "source_reported_version",
    "acquisition_completed_utc",
    "archive_filename",
    "archive_size_bytes",
    "archive_sha256",
    "pipeline_input_filename",
    "pipeline_input_size_bytes",
    "pipeline_input_sha256",
    "declared_license",
    "status",
}
REQUIRED_LENDINGCLUB_COLUMNS = {"issue_d", "loan_status"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_within(root: Path, relative_name: str) -> Path:
    path = (root / relative_name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Manifest path escapes the raw-data root: {relative_name!r}")
    return path


def _verify_file(
    raw_root: Path,
    relative_name: str,
    expected_size: str,
    expected_hash: str,
) -> dict[str, Any]:
    path = _resolve_within(raw_root, relative_name)
    if not path.is_file():
        raise FileNotFoundError(f"Acquired file is missing: {path}")
    size = path.stat().st_size
    if size != int(expected_size):
        raise ValueError(f"Size mismatch for {path}: expected {expected_size}, found {size}")
    observed_hash = _sha256(path)
    if observed_hash != expected_hash.lower():
        raise ValueError(
            f"SHA-256 mismatch for {path}: expected {expected_hash}, found {observed_hash}"
        )
    return {
        "path": str(path),
        "size_bytes": size,
        "sha256": observed_hash,
    }


def _find_csv_header(stream: TextIO, *, maximum_lines: int = 10) -> set[str]:
    for _ in range(maximum_lines):
        line = stream.readline()
        if not line:
            break
        columns = {value.strip().strip('"') for value in next(csv.reader([line]))}
        if REQUIRED_LENDINGCLUB_COLUMNS.issubset(columns):
            return columns
    raise ValueError("Could not find a LendingClub CSV header containing issue_d and loan_status")


def _validate_lendingclub(raw_root: Path, row: dict[str, str]) -> dict[str, Any]:
    archive = _resolve_within(raw_root, row["archive_filename"])
    pipeline_input = _resolve_within(raw_root, row["pipeline_input_filename"])
    with gzip.open(
        archive,
        mode="rt",
        encoding="utf-8-sig",
        errors="replace",
        newline="",
    ) as stream:
        archive_columns = _find_csv_header(stream)
    with pipeline_input.open(encoding="utf-8-sig", errors="replace", newline="") as stream:
        input_columns = _find_csv_header(stream)
    if archive_columns != input_columns:
        raise ValueError("LendingClub archive and extracted-input headers differ")
    return {
        "header_column_count": len(input_columns),
        "required_columns_present": sorted(REQUIRED_LENDINGCLUB_COLUMNS),
    }


def _validate_german_credit(raw_root: Path, row: dict[str, str]) -> dict[str, Any]:
    pipeline_input = _resolve_within(raw_root, row["pipeline_input_filename"])
    target_counts: Counter[str] = Counter()
    rows = 0
    width: int | None = None
    missing_fields = 0
    with pipeline_input.open(encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            values = line.split()
            if not values:
                continue
            width = width or len(values)
            if len(values) != width:
                raise ValueError(
                    f"Inconsistent German Credit row width at line {line_number}: {len(values)}"
                )
            missing_fields += sum(value == "?" for value in values)
            target_counts[values[-1]] += 1
            rows += 1
    if (
        rows != 1000
        or width != 21
        or missing_fields
        or target_counts != Counter({"1": 700, "2": 300})
    ):
        raise ValueError(
            "Unexpected German Credit structure: "
            f"rows={rows}, columns={width}, missing={missing_fields}, "
            f"targets={dict(target_counts)}"
        )
    return {
        "rows": rows,
        "columns_including_target": width,
        "missing_fields": missing_fields,
        "target_counts": dict(sorted(target_counts.items())),
    }


def validate_acquisitions(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    raw_root = manifest_path.parent.resolve()
    with manifest_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or ())
        missing_columns = sorted(REQUIRED_MANIFEST_COLUMNS - columns)
        if missing_columns:
            raise ValueError(f"Acquisition manifest is missing columns: {missing_columns}")
        rows = list(reader)

    acquired = [row for row in rows if row["status"].startswith("acquired_verified")]
    source_ids = [row["source_id"] for row in rows]
    duplicates = sorted(source for source, count in Counter(source_ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate source_id values: {duplicates}")
    if not acquired:
        raise ValueError("The acquisition manifest contains no verified acquisitions")

    sources: list[dict[str, Any]] = []
    for row in acquired:
        if not row["acquisition_completed_utc"]:
            raise ValueError(f"Missing acquisition timestamp for {row['source_id']}")
        source_result: dict[str, Any] = {
            "source_id": row["source_id"],
            "role": row["role"],
            "status": row["status"],
            "source_reported_version": row["source_reported_version"],
            "declared_license": row["declared_license"],
            "archive": _verify_file(
                raw_root,
                row["archive_filename"],
                row["archive_size_bytes"],
                row["archive_sha256"],
            ),
            "pipeline_input": _verify_file(
                raw_root,
                row["pipeline_input_filename"],
                row["pipeline_input_size_bytes"],
                row["pipeline_input_sha256"],
            ),
        }
        if row["source_id"] == "lendingclub_kaggle_v3":
            source_result["structural_validation"] = _validate_lendingclub(raw_root, row)
        elif row["source_id"] == "uci_statlog_german_144":
            source_result["structural_validation"] = _validate_german_credit(raw_root, row)
        sources.append(source_result)

    return {
        "status": "passed",
        "manifest": str(manifest_path),
        "manifest_row_count": len(rows),
        "verified_acquisition_count": len(acquired),
        "sources": sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=Path("data/raw/acquisition_manifest.csv"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_acquisitions(args.manifest)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
