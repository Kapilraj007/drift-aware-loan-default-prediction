"""Compare two Sprint 1 feature stores on reproducibility-critical content."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inventory_digest(root: Path, variant: str) -> tuple[str, dict[str, str]]:
    variant_root = root / variant
    files = sorted(variant_root.rglob("*.parquet"))
    if not files:
        raise ValueError(f"No Parquet files under {variant_root}")
    inventory = {
        path.relative_to(variant_root).as_posix(): _sha256(path) for path in files
    }
    digest = hashlib.sha256()
    for name, file_hash in inventory.items():
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest(), inventory


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def compare_feature_stores(left: Path, right: Path) -> dict[str, Any]:
    left = left.expanduser().resolve()
    right = right.expanduser().resolve()
    left_manifest = _read_json(left / "manifest.json")
    right_manifest = _read_json(right / "manifest.json")

    stable_manifest_fields = (
        "schema_version",
        "layout_version",
        "format",
        "parquet_engine",
        "compression",
        "partition_column",
        "date_column",
        "target_column",
        "split_column",
        "variants",
        "feature_names",
        "feature_dtypes",
        "row_counts",
        "total_rows",
        "partitions",
        "minimum_issue_quarter",
        "maximum_issue_quarter",
        "quarter_to_split",
        "data_dictionary_sha256",
        "pipeline_metadata",
    )
    manifest_mismatches = [
        field
        for field in stable_manifest_fields
        if left_manifest.get(field) != right_manifest.get(field)
    ]
    if manifest_mismatches:
        raise ValueError(f"Stable manifest fields differ: {manifest_mismatches}")

    if (left / "data_dictionary.csv").read_bytes() != (
        right / "data_dictionary.csv"
    ).read_bytes():
        raise ValueError("Run data dictionaries are not byte-identical")

    left_metadata = _read_json(left / "artifacts" / "feature_metadata.json")
    right_metadata = _read_json(right / "artifacts" / "feature_metadata.json")
    left_metadata.pop("fitted_at_utc", None)
    right_metadata.pop("fitted_at_utc", None)
    if left_metadata != right_metadata:
        raise ValueError("Fitted preprocessing contracts differ after removing timestamps")

    variant_digests: dict[str, str] = {}
    partition_counts: dict[str, int] = {}
    for variant in ("unscaled", "scaled"):
        left_digest, left_inventory = _inventory_digest(left, variant)
        right_digest, right_inventory = _inventory_digest(right, variant)
        if left_inventory != right_inventory:
            changed = sorted(
                set(left_inventory)
                ^ set(right_inventory)
                | {
                    name
                    for name in set(left_inventory) & set(right_inventory)
                    if left_inventory[name] != right_inventory[name]
                }
            )
            raise ValueError(f"{variant} Parquet content differs: {changed[:10]}")
        if left_digest != right_digest:  # pragma: no cover - implied by inventories
            raise ValueError(f"{variant} inventory digests differ")
        variant_digests[variant] = left_digest
        partition_counts[variant] = len(left_inventory)

    return {
        "status": "passed",
        "left": str(left),
        "right": str(right),
        "stable_manifest_fields_verified": len(stable_manifest_fields),
        "data_dictionary_byte_identical": True,
        "preprocessing_contract_identical_ignoring_timestamp": True,
        "partition_counts": partition_counts,
        "parquet_inventory_sha256": variant_digests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare_feature_stores(args.left, args.right)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
