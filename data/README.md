# Data, temporal splits, and models

This document is the data and modeling companion to the
[project README](../README.md). It describes what data the project uses, how
resolved loans are split without temporal leakage, and which models are
trained and evaluated.

Raw and derived datasets are local artifacts and are not committed. The
repository contains provenance, schemas, code, and tests; it does not grant a
right to redistribute source records.

All row-level datasets, Parquet feature stores, preprocessors, and model
artifacts remain on this machine. Hosted Neon contains only application,
prediction, feedback, monitoring, authorization, and audit records.

## Dataset and prediction target

The primary dataset is the LendingClub accepted-loan history covering issue
quarters 2007Q2 through 2018Q4. The pipeline loads only an explicit
application-time predictor allowlist. Post-origination fields such as payments,
recoveries, hardship outcomes, and later credit pulls are denied to prevent
target leakage.

The binary target is built from `loan_status`:

- `Charged Off` and `Default` become class `1` (default).
- `Fully Paid` becomes class `0` (non-default).
- unresolved or in-progress statuses are excluded and counted in the build
  manifest.

The verified run scanned 2,260,701 source rows and retained 1,345,350 resolved
loans: 1,076,751 non-default and 268,599 default/charged-off observations.

UCI Statlog German Credit is preserved as a secondary benchmark for a later
cross-dataset evaluation. It is not mixed into the LendingClub training data.

## Train, validation, and test split

The project uses a chronological 60%/20%/20% allocation of complete issue
quarters, not a random row split. Keeping a quarter intact prevents future
loans from leaking into earlier training data and makes the last window an
honest test of temporal shift.

| Dataset role | Internal name | Issue quarters | Quarters | Rows | Used for |
| --- | --- | --- | ---: | ---: | --- |
| Train | `train` | 2007Q2-2014Q1 | 28 | 274,970 | Fit the transformer, scaler, and models |
| Validation | `validation` | 2014Q2-2016Q2 | 9 | 726,519 | Model selection and F1 threshold selection |
| Test | `shift` | 2016Q3-2018Q4 | 10 | 343,861 | Locked final evaluation under later-time shift |

The code and artifacts call the test set `shift` because it is deliberately
the newest time window and doubles as the distribution-shift holdout. It is
not used to fit preprocessing, model parameters, or prediction thresholds.
The unequal row counts are expected: the fractions allocate quarters, while
LendingClub volume varies substantially by quarter.

The exact boundaries and counts are recorded in
`processed/feature_store/manifest.json` when the feature store is built. The
split implementation is in
[`../src/drift_loan/data/splits.py`](../src/drift_loan/data/splits.py).

## Preprocessing and feature views

The transformer is fitted only on the training window and then frozen for the
validation and test windows. It produces 53 model features, including:

- numeric application and credit attributes with training-only median
  imputation and matching missing-value flags;
- fixed ordinal encodings for grade and sub-grade;
- training-only one-hot vocabularies for purpose and home ownership; and
- engineered loan-to-income, installment-to-income, and credit-history-years
  features.

Two Parquet views are written for every issue quarter:

- `unscaled` is used by LightGBM and XGBoost;
- `scaled` applies a training-fitted StandardScaler and is used by logistic
  regression.

## Models used

| Model | Role | Feature view | Key controls |
| --- | --- | --- | --- |
| LightGBM | Primary production-candidate research model | Unscaled | Class-balanced binary objective, deterministic seeded training |
| XGBoost | Tree-model robustness cross-check | Unscaled | Histogram trees and class-imbalance weighting |
| L2 logistic regression | Linear and interpretable baseline | Scaled | Balanced classes, L2 regularization |

Model settings are selected with three expanding-window temporal folds. Each
model's decision threshold is selected on the validation set by F1. The test
window remains locked until final evaluation. LightGBM is the persisted primary
model; its tree explainer supplies SHAP values, and ADWIN monitors the score
stream for change.

### Verified model results

| Model | Validation ROC-AUC | Validation PR-AUC | Validation F1 | Test ROC-AUC | Test PR-AUC | Test F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LightGBM | 0.7188 | 0.3904 | 0.4412 | 0.6948 | 0.3817 | 0.4418 |
| XGBoost | 0.7185 | 0.3912 | 0.4407 | 0.6932 | 0.3798 | 0.4398 |
| L2 logistic regression | 0.7159 | 0.3857 | 0.4395 | 0.6898 | 0.3706 | 0.4378 |

These results come from `artifacts/model/metrics.json`. They are research and
decision-support metrics, not an automated approval or denial policy. Late
2018 labels have maturity limitations, so per-quarter results should be read
alongside aggregate metrics.

## Expected layout

```text
data/
  raw/
    accepted_2007_to_2018Q4.csv.gz
    accepted_loans.csv
    statlog_german_credit_data.zip
    uci_statlog_german_144/german.data
    acquisition_manifest.csv
  artifacts/
    preprocessor/
  interim/
  processed/
    feature_store/
      unscaled/issue_quarter=YYYYQn/
      scaled/issue_quarter=YYYYQn/
      artifacts/
      manifest.json
reports/
  generated/
    eda/
```

Only this README, empty-directory sentinels, and the acquisition manifest belong
in version control under `data/`. Raw dataset bytes and derived row-level
artifacts remain ignored. Preserve source compression and treat files under
`raw/` as immutable.

## Primary acquisition

1. Review [`../docs/data_provenance.md`](../docs/data_provenance.md), the
   [Kaggle mirror page](https://www.kaggle.com/datasets/wordsforthewise/lending-club),
   and the applicable Kaggle terms.
2. Download dataset reference `wordsforthewise/lending-club` using Kaggle's UI
   or official API, authenticating when required. Do not automate around an
   access or terms prompt.
3. Extract only `accepted_2007_to_2018Q4.csv.gz` and materialize its CSV as the
   configured path `data/raw/accepted_loans.csv`. Preserve the source archive
   when storage permits. Do not mix the rejected-loan file into the supervised
   dataset.
4. Add or update the `lendingclub_kaggle_v3` row in
   `data/raw/acquisition_manifest.csv` with the UTC timestamp, exact version,
   archive and pipeline-input byte sizes and SHA-256 digests, tool/authentication
   mode, license references, operator, and decompression/rename record.
5. Keep the archive and manifest together. A later download is a new source
   version even when the file name is unchanged.

On PowerShell, the digest can be captured without reading data into an editor:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath data/raw/accepted_2007_to_2018Q4.csv.gz
```

## Secondary acquisition

The default benchmark is UCI Statlog German Credit Data, DOI
[`10.24432/C5NC77`](https://doi.org/10.24432/C5NC77). Record the exact selected
file (`german.data` by default), acquisition timestamp, byte size, and SHA-256.
Retain the UCI citation, CC BY 4.0 link, and a note describing any label or
schema adaptation. Australian Credit Approval is an alternative, not an
unrecorded additional benchmark.

## Running the EDA notebook

Use the deterministic notebook runner so the input hash and aggregate output
paths are explicit:

```powershell
& .\.venv\Scripts\python.exe scripts\execute_eda_notebook.py `
  --data data\raw\accepted_loans.csv `
  --output-notebook reports\generated\01_eda_executed.ipynb `
  --output-dir reports\generated\eda
```

The notebook reads only `loan_status` and `issue_d` in chunks. If no input is
present, it exits its analysis cells cleanly with configuration guidance; it
does not substitute synthetic observations or publish placeholder findings.
The runner enables input hashing. Archive the generated CSV, PNG, JSON, and
executed notebook with the source manifest and code revision for a publication
run.

## Rebuild the split and train the models

After acquiring `raw/accepted_loans.csv`, create the leakage-safe feature store:

```powershell
& .\.venv\Scripts\python.exe -m drift_loan build `
  --config config\pipeline.json `
  --overwrite
```

From the project root, train all three model families and write their versioned
artifacts:

```powershell
& .\.venv\Scripts\python.exe -m drift_loan train-model `
  --feature-store data\processed\feature_store `
  --model-directory data\artifacts\model `
  --overwrite
```

The random seed and split fractions are in
[`../config/pipeline.json`](../config/pipeline.json). Model metadata, thresholds,
hashes, and time windows are written under `artifacts/model/`.

## Current verified local run

The archive and extracted input were verified on 2026-09-27 UTC. The real-data
feature store contains 1,345,350 resolved loans in 47 quarterly partitions and
passes `scripts/validate_feature_store.py`. The executed notebook and aggregate
reports are under `reports/generated/`; the build manifest and fitted artifacts
are under `data/processed/feature_store/` and `data/artifacts/preprocessor/`.
The official UCI German Credit ZIP and selected `german.data` benchmark were
also acquired and verified on 2026-09-28; their exact hashes are recorded in
the acquisition manifest, while their schema adapter remains deferred to the
later cross-dataset model evaluation.
