# Sprint 2 completion report

## Status

Sprint 2 is complete against the real, frozen LendingClub feature store. The
implementation adds reproducible temporal model training, LightGBM
explanations, KS and ADWIN drift monitoring, and an authenticated FastAPI
decision-support backend. It does not make automated lending decisions.

## Training protocol

- Training: 274,970 loans from 2007Q2 through 2014Q1.
- Validation: 726,519 loans from 2014Q2 through 2016Q2. It selects the
  operating threshold by F1 and is the only split used for that choice.
- Shift holdout: 343,861 loans from 2016Q3 through 2018Q4. It remains out of
  model and threshold selection.
- Candidate selection uses three expanding windows of complete issue quarters.
  The Sprint 1 transformer remains frozen from the whole training window; the
  metadata records this limitation for fully nested preprocessing studies.
- The primary model is a class-balanced LightGBM classifier. XGBoost is a
  robustness cross-check, and L2 logistic regression is the scaled-feature
  interpretability baseline.

## Measured model results

All metrics below use the threshold selected on the validation split for that
same model. PR-AUC is average precision and KS is the maximum TPR minus FPR.

| Model | Split | ROC-AUC | PR-AUC | KS | Brier | Precision | Recall | F1 | Accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LightGBM primary | Validation | 0.7188 | 0.3904 | 0.3187 | 0.2042 | 0.3405 | 0.6266 | 0.4412 | 0.6768 |
| LightGBM primary | Shift holdout | 0.6948 | 0.3817 | 0.2818 | 0.2121 | 0.3518 | 0.5937 | 0.4418 | 0.6617 |
| XGBoost cross-check | Validation | 0.7185 | 0.3912 | 0.3175 | 0.2057 | 0.3410 | 0.6228 | 0.4407 | 0.6780 |
| XGBoost cross-check | Shift holdout | 0.6932 | 0.3798 | 0.2789 | 0.2138 | 0.3519 | 0.5861 | 0.4398 | 0.6632 |
| Logistic baseline | Validation | 0.7159 | 0.3857 | 0.3149 | 0.2021 | 0.3436 | 0.6100 | 0.4395 | 0.6832 |
| Logistic baseline | Shift holdout | 0.6898 | 0.3706 | 0.2753 | 0.2163 | 0.3478 | 0.5907 | 0.4378 | 0.6579 |

The primary LightGBM decision threshold is 0.5093. On validation it produced
92,711 true positives, 398,973 true negatives, 179,585 false positives, and
55,250 false negatives. On the held-out shift set it produced 46,041 true
positives, 181,482 true negatives, 84,830 false positives, and 31,508 false
negatives.

The primary model therefore discriminates materially above chance on both
chronological evaluation periods, but it is not "correct" for every applicant:
the selected operating point trades precision for recall and must remain a
human-review risk flag rather than an approval or denial rule.

## Quarter-level finding

The shift performance report confirms the known label-maturity issue. The
primary model's ROC-AUC is 0.7021 in 2017Q3 and 0.7110 in 2018Q2, but falls to
0.5623 in 2018Q4, which has only 122 recorded defaults among 5,030 retained
rows. Its 2018Q4 PR-AUC is 0.0412 and F1 is 0.0532. These late outcomes are
not mature enough to support a current-deployment claim; the report preserves
the per-quarter results rather than hiding them in an aggregate score.

## Produced artifacts

The version `s2-f3815e4a8c475286` is stored under
`data/artifacts/model/` and includes:

- `model.joblib`, the LightGBM primary model;
- `xgboost_model.joblib` and `logistic_regression_model.joblib`;
- `shap_explainer.joblib`, a persisted LightGBM TreeExplainer;
- `adwin_detector.joblib`, calibrated from chronological validation scores;
- `feature_schema.json`, `metadata.json`, and `metrics.json`, with schema and
  artifact integrity hashes; and
- `reports/generated/sprint2_model_evaluation.json`, including validation and
  held-out per-quarter metrics.

## Backend and monitoring

The FastAPI service provides JWT role-based access for loan officers, risk
analysts, and administrators; applications, predictions, and officer feedback
are persisted with timestamps and detector state. It exposes a model metadata
endpoint, a top-three SHAP narrative, authenticated KS feature-drift checks,
and a process-local ADWIN score stream. Docker Compose defines PostgreSQL,
Redis, the API, and an optional Celery worker profile.

## Verification

- Real-data model training completed successfully with all three model
  families, persisted artifacts, and validation-only thresholds.
- Artifact loading validated model, schema, SHAP-explainer, and detector
  integrity hashes.
- A real FastAPI prediction request returned a score, threshold-based risk
  flag, persisted TreeSHAP explanation, detector state, and audit record.
- Full automated regression suite: 42 passed. The 28 warnings are limited to
  one Starlette deprecation and 27 scikit-learn logistic-solver warnings.
- Ruff reports no lint errors. `pip check` reports no broken requirements, and
  `docker compose --env-file .env.example --profile queue config --quiet`
  validates successfully.

## Remaining operational limits

- The public LendingClub data is historical and cannot justify a live lending
  deployment.
- Grade, sub-grade, and interest rate are valid under this project's stated
  origination-time contract, but not for a pre-offer score unless that feature
  availability is established and the model is retrained.
- The Celery worker provides safe queue wiring and health checks. A
  production training-job API needs institution-specific authorization,
  artifact promotion, and deployment controls before it should be enabled.
