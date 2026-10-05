"""Population KS checks and lazy online score-drift state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ..core.config import Settings


@dataclass(frozen=True, slots=True)
class FeatureDriftResult:
    feature: str
    statistic: float
    p_value: float
    drift_detected: bool
    reference_count: int
    current_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DriftSnapshot:
    status: str
    score_stream_count: int
    latest_score: float | None
    adwin_change_detected: bool
    feature_drift_count: int
    updated_at: datetime | None
    feature_results: tuple[FeatureDriftResult, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "score_stream_count": self.score_stream_count,
            "latest_score": self.latest_score,
            "adwin_change_detected": self.adwin_change_detected,
            "feature_drift_count": self.feature_drift_count,
            "updated_at": self.updated_at,
            "feature_results": [item.to_dict() for item in self.feature_results],
        }


class DriftService:
    """Maintains process-local detector state and auditable KS results.

    River is only imported when the first score reaches this service.  If a
    fitted detector is persisted at ``adwin_detector.joblib`` it is loaded
    first; otherwise a fresh ADWIN instance starts from the next score.  This
    allows API unit tests and non-monitoring deployments to run without a
    streaming service.
    """

    _METADATA_COLUMNS = frozenset({"target", "issue_d", "issue_quarter", "dataset_split"})

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._detector: Any | None = None
        self._detector_loaded = False
        self._score_stream_count = 0
        self._latest_score: float | None = None
        self._adwin_change_detected = False
        self._feature_results: tuple[FeatureDriftResult, ...] = ()
        self._updated_at: datetime | None = None

    def _load_detector(self) -> Any | None:
        if self._detector_loaded:
            return self._detector
        self._detector_loaded = True
        state_path = Path(self.settings.model_artifact_directory) / "adwin_detector.joblib"
        if state_path.is_file():
            try:
                self._detector = joblib.load(state_path)
                return self._detector
            except Exception:
                # State is optional: an invalid old state must not prevent a
                # newly deployed model from receiving human-review scores.
                self._detector = None
        try:
            from river.drift import ADWIN
        except ImportError:
            return None
        self._detector = ADWIN()
        return self._detector

    @staticmethod
    def _detector_changed(detector: Any) -> bool:
        return bool(
            getattr(detector, "drift_detected", getattr(detector, "change_detected", False))
        )

    def observe_score(self, score: float) -> DriftSnapshot:
        """Add a probability to the time-ordered stream and return its state."""

        value = float(score)
        if not np.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("score must be a finite probability between zero and one")
        detector = self._load_detector()
        changed = False
        if detector is not None:
            detector.update(value)
            changed = self._detector_changed(detector)
        self._score_stream_count += 1
        self._latest_score = value
        self._adwin_change_detected = changed
        self._updated_at = datetime.now(UTC)
        return self.snapshot()

    def rehydrate(
        self,
        scores: list[float],
        persisted_snapshot: dict[str, object] | None = None,
    ) -> DriftSnapshot:
        """Replay persisted scores into a fresh detector and restore KS state."""

        self._detector = None
        self._detector_loaded = True
        try:
            from river.drift import ADWIN
        except ImportError:
            self._detector = None
        else:
            self._detector = ADWIN()
        self._score_stream_count = 0
        self._latest_score = None
        self._adwin_change_detected = False
        self._feature_results = ()
        self._updated_at = None
        for score in scores:
            self.observe_score(float(score))

        if persisted_snapshot:
            raw_results = persisted_snapshot.get("feature_results", [])
            if isinstance(raw_results, list):
                restored: list[FeatureDriftResult] = []
                for item in raw_results:
                    if not isinstance(item, dict):
                        continue
                    try:
                        restored.append(
                            FeatureDriftResult(
                                feature=str(item["feature"]),
                                statistic=float(item["statistic"]),
                                p_value=float(item["p_value"]),
                                drift_detected=bool(item["drift_detected"]),
                                reference_count=int(item["reference_count"]),
                                current_count=int(item["current_count"]),
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                self._feature_results = tuple(restored)
            persisted_count = persisted_snapshot.get("score_stream_count")
            if isinstance(persisted_count, int):
                self._score_stream_count = max(self._score_stream_count, persisted_count)
            if not scores:
                latest_score = persisted_snapshot.get("latest_score")
                if isinstance(latest_score, int | float):
                    self._latest_score = float(latest_score)
            self._adwin_change_detected = self._adwin_change_detected or bool(
                persisted_snapshot.get("adwin_change_detected", False)
            )
            raw_updated_at = persisted_snapshot.get("updated_at")
            if isinstance(raw_updated_at, datetime):
                self._updated_at = raw_updated_at
            elif isinstance(raw_updated_at, str):
                try:
                    self._updated_at = datetime.fromisoformat(
                        raw_updated_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass
        return self.snapshot()

    @staticmethod
    def _common_numeric_columns(reference: pd.DataFrame, current: pd.DataFrame) -> list[str]:
        common = [column for column in reference.columns if column in current.columns]
        candidates: list[str] = []
        for column in common:
            if column in DriftService._METADATA_COLUMNS:
                continue
            reference_numeric = pd.to_numeric(reference[column], errors="coerce")
            current_numeric = pd.to_numeric(current[column], errors="coerce")
            if reference_numeric.notna().sum() >= 2 and current_numeric.notna().sum() >= 2:
                candidates.append(str(column))
        return candidates

    def evaluate_feature_drift(
        self,
        reference: pd.DataFrame,
        current: pd.DataFrame,
        *,
        alpha: float = 0.01,
    ) -> DriftSnapshot:
        """Run a two-sample KS test for each common numeric feature."""

        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be strictly between zero and one")
        if reference.empty or current.empty:
            raise ValueError("Both reference and current cohorts must contain rows")
        try:
            from scipy.stats import ks_2samp
        except ImportError as exc:  # pragma: no cover - scipy is sklearn's dependency
            raise RuntimeError("scipy is required for KS drift checks") from exc

        results: list[FeatureDriftResult] = []
        for feature in self._common_numeric_columns(reference, current):
            reference_values = (
                pd.to_numeric(reference[feature], errors="coerce").dropna().to_numpy()
            )
            current_values = pd.to_numeric(current[feature], errors="coerce").dropna().to_numpy()
            test = ks_2samp(reference_values, current_values, method="auto")
            results.append(
                FeatureDriftResult(
                    feature=feature,
                    statistic=float(test.statistic),
                    p_value=float(test.pvalue),
                    drift_detected=bool(test.pvalue < alpha),
                    reference_count=int(len(reference_values)),
                    current_count=int(len(current_values)),
                )
            )
        self._feature_results = tuple(results)
        self._updated_at = datetime.now(UTC)
        return self.snapshot()

    def snapshot(self) -> DriftSnapshot:
        feature_drift_count = sum(item.drift_detected for item in self._feature_results)
        if self._adwin_change_detected or feature_drift_count:
            status = "drift_detected"
        elif self._score_stream_count:
            status = "stable"
        else:
            status = "not_observed"
        return DriftSnapshot(
            status=status,
            score_stream_count=self._score_stream_count,
            latest_score=self._latest_score,
            adwin_change_detected=self._adwin_change_detected,
            feature_drift_count=feature_drift_count,
            updated_at=self._updated_at,
            feature_results=self._feature_results,
        )
