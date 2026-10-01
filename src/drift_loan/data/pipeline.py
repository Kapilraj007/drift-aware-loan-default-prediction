"""High-level Sprint 1 pipeline orchestration suitable for a CLI or job runner."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .data_dictionary import build_run_data_dictionary
from .feature_store import FeatureStoreWriteResult, write_partitioned_feature_store
from .ingestion import IngestionMetadata, ingest_lendingclub_csv
from .splits import TemporalSplitMetadata, temporal_train_validation_shift_split
from .streaming import build_streaming_feature_store
from .transform import LoanFeatureTransformer, transform_features

_STREAMING_THRESHOLD_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class PipelineBuildResult:
    """Complete output contract for a successful feature-store build."""

    feature_store_root: Path
    manifest_path: Path
    artifact_directory: Path
    data_dictionary_path: Path
    ingestion: IngestionMetadata
    temporal_split: TemporalSplitMetadata
    feature_names: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_store_root": str(self.feature_store_root),
            "manifest_path": str(self.manifest_path),
            "artifact_directory": str(self.artifact_directory),
            "data_dictionary_path": str(self.data_dictionary_path),
            "ingestion": self.ingestion.to_dict(),
            "temporal_split": self.temporal_split.to_dict(),
            "feature_names": list(self.feature_names),
        }


def _should_stream(input_csv: str | Path | Sequence[str | Path]) -> bool:
    sources = (input_csv,) if isinstance(input_csv, str | Path) else input_csv
    total_bytes = 0
    try:
        for source in sources:
            path = Path(source).expanduser().resolve()
            if not path.is_file():
                return False
            total_bytes += path.stat().st_size
    except OSError:
        return False
    return total_bytes >= _STREAMING_THRESHOLD_BYTES


def _build_in_memory_feature_store(
    input_csv: str | Path | Sequence[str | Path],
    feature_store: str | Path,
    *,
    artifact_directory: str | Path | None,
    train_fraction: float,
    validation_fraction: float,
    shift_fraction: float | None,
    chunk_size: int | None,
    random_seed: int | None,
    overwrite: bool,
    parquet_engine: str,
) -> PipelineBuildResult:
    ingestion = ingest_lendingclub_csv(
        input_csv,
        require_target=True,
        chunk_size=chunk_size,
    )
    split = temporal_train_validation_shift_split(
        ingestion.frame,
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
        shift_fraction=shift_fraction,
        resolved_only=True,
    )

    transformer = LoanFeatureTransformer()
    train = transform_features(
        split.train,
        transformer=transformer,
        fit=True,
        include_target=True,
    )
    validation = transform_features(
        split.validation,
        transformer=transformer,
        include_target=True,
    )
    shift = transform_features(
        split.shift,
        transformer=transformer,
        include_target=True,
    )

    pipeline_metadata = {
        "ingestion": ingestion.metadata.to_dict(),
        "temporal_split": split.metadata.to_dict(),
        "chunk_size": chunk_size,
        "random_seed": random_seed,
        "fit_scope": "train_only",
        "execution_mode": "in_memory",
    }
    datasets = {"train": train, "validation": validation, "shift": shift}
    run_data_dictionary = build_run_data_dictionary(ingestion.frame, datasets)
    store_result: FeatureStoreWriteResult = write_partitioned_feature_store(
        datasets,
        feature_store,
        transformer=transformer,
        overwrite=overwrite,
        parquet_engine=parquet_engine,
        extra_metadata=pipeline_metadata,
        data_dictionary=run_data_dictionary,
    )

    selected_artifact_directory = store_result.artifact_directory
    if artifact_directory is not None:
        requested = Path(artifact_directory).expanduser().resolve()
        if requested != store_result.artifact_directory:
            transformer.save_artifacts(requested, overwrite=overwrite)
        selected_artifact_directory = requested

    if store_result.data_dictionary_path is None:  # pragma: no cover - invariant
        raise RuntimeError("Feature-store build did not return its required data dictionary.")

    return PipelineBuildResult(
        feature_store_root=store_result.root,
        manifest_path=store_result.manifest_path,
        artifact_directory=selected_artifact_directory,
        data_dictionary_path=store_result.data_dictionary_path,
        ingestion=ingestion.metadata,
        temporal_split=split.metadata,
        feature_names=transformer.feature_names_,
    )


def build_feature_store_from_csv(
    input_csv: str | Path | Sequence[str | Path],
    feature_store: str | Path,
    *,
    artifact_directory: str | Path | None = None,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    shift_fraction: float | None = None,
    chunk_size: int | None = None,
    random_seed: int | None = None,
    overwrite: bool = False,
    parquet_engine: str = "pyarrow",
) -> PipelineBuildResult:
    """Ingest, split, fit, and persist a deterministic feature store.

    Large sources automatically use a bounded-memory disk spool; small sources
    retain the simpler in-memory path. ``random_seed`` remains metadata because
    the core pipeline performs no random operation.
    """

    if not _should_stream(input_csv):
        return _build_in_memory_feature_store(
            input_csv,
            feature_store,
            artifact_directory=artifact_directory,
            train_fraction=train_fraction,
            validation_fraction=validation_fraction,
            shift_fraction=shift_fraction,
            chunk_size=chunk_size,
            random_seed=random_seed,
            overwrite=overwrite,
            parquet_engine=parquet_engine,
        )

    result = build_streaming_feature_store(
        input_csv,
        feature_store,
        artifact_directory=artifact_directory,
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
        shift_fraction=shift_fraction,
        chunk_size=chunk_size,
        random_seed=random_seed,
        overwrite=overwrite,
        parquet_engine=parquet_engine,
    )

    return PipelineBuildResult(
        feature_store_root=result.root,
        manifest_path=result.manifest_path,
        artifact_directory=result.artifact_directory,
        data_dictionary_path=result.data_dictionary_path,
        ingestion=result.ingestion,
        temporal_split=result.temporal_split,
        feature_names=result.feature_names,
    )
