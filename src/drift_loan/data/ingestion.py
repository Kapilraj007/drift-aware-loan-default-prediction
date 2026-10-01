"""Strict, deterministic ingestion for LendingClub accepted-loan CSV files."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .exceptions import SchemaValidationError
from .schema import (
    INGESTION_ALLOWLIST,
    LEAKAGE_COLUMNS,
    REQUIRED_INFERENCE_COLUMNS,
    REQUIRED_TRAINING_COLUMNS,
)

_HEADER_SCAN_LIMIT = 100
_NA_VALUES = ("", " ", "NA", "N/A", "n/a", "null", "NULL", "None")


@dataclass(frozen=True)
class IngestionMetadata:
    """Auditable facts about a CSV ingestion run."""

    source_files: tuple[str, ...]
    source_bytes: tuple[tuple[str, int], ...]
    source_sha256: tuple[tuple[str, str], ...]
    rows_read: int
    columns_loaded: tuple[str, ...]
    ignored_leakage_columns: tuple[str, ...]
    header_rows_skipped: tuple[tuple[str, int], ...]
    chunk_size: int | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass(frozen=True)
class IngestionResult:
    """A pruned input frame and its provenance metadata."""

    frame: pd.DataFrame
    metadata: IngestionMetadata


def _sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise_sources(
    sources: str | Path | Sequence[str | Path],
) -> tuple[Path, ...]:
    if isinstance(sources, str | Path):
        candidate_sources: Iterable[str | Path] = (sources,)
    else:
        candidate_sources = sources

    paths = [Path(source).expanduser().resolve() for source in candidate_sources]
    if not paths:
        raise SchemaValidationError("At least one LendingClub CSV source is required.")

    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SchemaValidationError(f"CSV source file(s) not found: {missing}")

    duplicates = sorted({str(path) for path in paths if paths.count(path) > 1})
    if duplicates:
        raise SchemaValidationError(f"Duplicate CSV source file(s): {duplicates}")

    # Source order must not depend on caller container ordering.
    return tuple(sorted(paths, key=lambda path: str(path).casefold()))


def _find_header(path: Path, required_columns: frozenset[str]) -> tuple[int, tuple[str, ...]]:
    """Locate the real CSV header, tolerating Kaggle preamble lines."""

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for line_number, line in enumerate(handle):
            if line_number >= _HEADER_SCAN_LIMIT:
                break
            try:
                fields = next(csv.reader([line]))
            except csv.Error:
                continue
            stripped = tuple(field.strip() for field in fields)
            if required_columns.issubset(stripped):
                return line_number, stripped

    required_preview = ", ".join(sorted(required_columns))
    raise SchemaValidationError(
        f"Could not locate a LendingClub header in {path} within the first "
        f"{_HEADER_SCAN_LIMIT} lines. Required columns: {required_preview}."
    )


def ingest_lendingclub_csv(
    sources: str | Path | Sequence[str | Path],
    *,
    require_target: bool = True,
    chunk_size: int | None = None,
) -> IngestionResult:
    """Read one or more LendingClub CSVs through an explicit feature allow-list.

    Files are processed in resolved-path order.  Only model inputs, the target,
    and the two date columns are loaded; post-origination fields never enter the
    returned frame.  A common Kaggle metadata line before the CSV header is
    detected automatically.
    """

    if chunk_size is not None and (isinstance(chunk_size, bool) or chunk_size <= 0):
        raise ValueError("chunk_size must be a positive integer or None.")

    paths = _normalise_sources(sources)
    required = REQUIRED_TRAINING_COLUMNS if require_target else REQUIRED_INFERENCE_COLUMNS
    frames: list[pd.DataFrame] = []
    ignored_leakage: set[str] = set()
    skipped: list[tuple[str, int]] = []

    for path in paths:
        header_line, header = _find_header(path, required)
        ignored_leakage.update(set(header) & LEAKAGE_COLUMNS)
        skipped.append((str(path), header_line))

        try:
            read_result = pd.read_csv(
                path,
                skiprows=header_line,
                usecols=lambda column: str(column).strip() in INGESTION_ALLOWLIST,
                na_values=_NA_VALUES,
                keep_default_na=True,
                low_memory=False,
                encoding="utf-8-sig",
                on_bad_lines="error",
                chunksize=chunk_size,
            )
            if isinstance(read_result, pd.DataFrame):
                frame = read_result
            else:
                chunks = list(read_result)
                frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        except (OSError, UnicodeError, pd.errors.ParserError, ValueError) as exc:
            raise SchemaValidationError(f"Failed to read LendingClub CSV {path}: {exc}") from exc

        frame = frame.rename(columns=lambda column: str(column).strip())
        if frame.columns.duplicated().any():
            duplicates = frame.columns[frame.columns.duplicated()].tolist()
            raise SchemaValidationError(f"Duplicate canonical column names in {path}: {duplicates}")

        missing = sorted(required - set(frame.columns))
        if missing:
            raise SchemaValidationError(f"LendingClub CSV {path} is missing columns: {missing}")

        # Preserve one canonical order across files and releases.
        selected_columns = [column for column in INGESTION_ALLOWLIST if column in frame.columns]
        frame = frame.loc[:, sorted(selected_columns)].copy()
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True, sort=False)
    if combined.empty:
        raise SchemaValidationError("LendingClub CSV ingestion produced zero rows.")

    combined = combined.reindex(sorted(combined.columns), axis=1)
    metadata = IngestionMetadata(
        source_files=tuple(str(path) for path in paths),
        source_bytes=tuple((str(path), path.stat().st_size) for path in paths),
        source_sha256=tuple((str(path), _sha256_file(path)) for path in paths),
        rows_read=len(combined),
        columns_loaded=tuple(combined.columns),
        ignored_leakage_columns=tuple(sorted(ignored_leakage)),
        header_rows_skipped=tuple(skipped),
        chunk_size=chunk_size,
    )
    return IngestionResult(frame=combined, metadata=metadata)


def load_lendingclub_csv(
    sources: str | Path | Sequence[str | Path],
    *,
    require_target: bool = True,
    chunk_size: int | None = None,
) -> pd.DataFrame:
    """Convenience wrapper returning only the pruned DataFrame."""

    return ingest_lendingclub_csv(
        sources,
        require_target=require_target,
        chunk_size=chunk_size,
    ).frame
