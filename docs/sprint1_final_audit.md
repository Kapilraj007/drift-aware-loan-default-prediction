# Sprint 1 Final Audit

## Conclusion

Sprint 1 is complete against Section 2 of the project plan as of 2026-09-29.
The repository foundation, primary and selected-secondary acquisition,
preprocessing, feature store, EDA, data dictionary, provenance, deterministic
temporal splitting, drift-simulation harness, automated tests, reproducibility
checks, and executable Docker image all pass. No open Sprint 1 requirement was
found.

This audit treats Section 2 as the scope boundary. It does not count the model,
FastAPI application, React interface, production monitoring, or publication
study from later sections as Sprint 1 deliverables.

## Foundation and reproducibility

| Plan requirement | Result | Evidence |
| --- | --- | --- |
| Initialize `data`, `notebooks`, `backend`, `frontend`, `docs`, and `monitoring` | Passed | All six directories exist; each future subsystem has an explicit boundary or README |
| Pin dependencies | Passed | `requirements.txt`, `requirements-dev.txt`, and `pyproject.toml` pin the runtime, development, and build dependencies |
| Provide a reproducible Dockerfile | Passed | Image `drift-loan-sprint1:verified` built and launched; exact image identity is recorded in `reports/generated/docker_validation.json` |
| Use one transform implementation for training and future serving | Passed | `LoanFeatureTransformer` is used by the pipeline and re-exported by `backend/app/ml/transform_features.py` |
| Keep the system assistive and human-gated | Passed | README states that Sprint 1 is decision-support infrastructure and does not approve, decline, or train a production model |

## Data sources and acquisition

| Plan source | Result | Evidence |
| --- | --- | --- |
| LendingClub accepted loans, 2007-2018 | Passed | Official Kaggle mirror artifact acquired: 392,582,231-byte archive and 1,675,133,810-byte extracted CSV; both hashes match the acquisition manifest |
| UCI German Credit or an allowed alternative | Passed | Default UCI German Credit ZIP and `german.data` acquired from UCI; exact hashes recorded; 1,000 rows and 700/300 classes structurally verified |
| `issue_d` as the temporal-shift source | Passed | Parsed to canonical quarters, used for partitioning, chronological splits, arbitrary windows, and real 2018Q4 drift verification |
| Faker metadata for the later demo UI | Correctly deferred | Source and constraints are documented; Faker is not installed because applicant-name generation is a later UI task and must never enter training |
| No live bureau API or scraping | Passed | Pipeline is fully file-based and introduces no unnecessary regulated-data integration |

`data/raw/acquisition_manifest.csv` is the acquisition system of record.
`reports/generated/acquisition_validation.json` rehashed both selected sources
and passed their structural checks. Raw bytes remain ignored by version control.

## Input, target, and leakage controls

| Plan requirement | Result | Evidence |
| --- | --- | --- |
| LendingClub CSV with approximately 150 columns | Passed | Acquired input header contains 151 columns |
| One row per loan application or origination | Passed | Ingestion preserves the accepted-loan row as the unit of observation and rejects duplicate input paths |
| Map `Charged Off` and `Default` to `1`; `Fully Paid` to `0` | Passed | Real run produced 268,599 positive and 1,076,751 negative resolved outcomes |
| Exclude unresolved outcomes | Passed | 915,351 current, grace, late, policy-status, or missing outcomes were counted and excluded |
| Exclude post-origination leakage fields | Passed | Explicit denylist is documented and persisted; the validator found an empty leakage-feature intersection |
| Retain the specified applicant, loan, employment, and housing predictors | Passed | Production schema contains every specified source group and only allowlisted predictors or their documented derivatives |

## Preprocessing and feature engineering

| Plan requirement | Result | Evidence |
| --- | --- | --- |
| Numeric median imputation with missing flags | Passed | Medians are fit on training quarters only; all numeric and engineered values have `*_was_missing` indicators |
| Ordinal grade and sub-grade encoding | Passed | Fixed target-independent mappings include an unknown-category sentinel |
| One-hot purpose and home ownership | Passed | Training-only vocabularies are frozen and unknown future categories are handled safely |
| Preserve an unscaled tree view and a StandardScaler view | Passed | All 47 quarters exist in both `unscaled` and `scaled`; scaled training means are within `8.09e-16` of zero |
| `loan_to_income` | Passed | Safe-divide implementation, missing flag, dictionary entry, and automated tests |
| `credit_history_years` | Passed | Derived from `earliest_cr_line` and `issue_d`, with invalid negative histories treated as missing |
| `installment_to_income` | Passed | Monthly-income ratio implemented with safe division, missing flag, dictionary entry, and tests |
| Defer imbalance treatment to model training | Passed | No synthetic oversampling is applied; the measured default share is 19.965%, and class weighting remains a Sprint 2 model setting |

## Feature store and temporal data flow

| Plan requirement | Result | Evidence |
| --- | --- | --- |
| CSV to cleaning code to Parquet | Passed | Bounded-memory production pipeline processed the 1.68 GB CSV and wrote Snappy Parquet |
| Partition by issue quarter | Passed | 47 complete partitions span 2007Q2 through 2018Q4 |
| Deterministic time split | Passed | 274,970 train rows, 726,519 validation rows, and 343,861 latest-quarter shift rows; no random row shuffle |
| Train-only fitted state | Passed | Imputation, one-hot vocabularies, and scaling are fit only on the training quarters and persisted |
| Persist reusable preprocessing artifacts | Passed | Internal and external transformer/metadata copies have matching hashes |
| Produce a data dictionary with the six required columns | Passed | Static and run-specific dictionaries contain `feature_name`, `dtype`, `source_column`, `null_rate`, `transformation_applied`, and `leakage_risk_flag` |

The partition validator found 1,345,350 total rows, 53 production features,
zero missing or non-finite model values, valid binary targets, chronological
partition metadata, and matching acquisition, dictionary, and artifact hashes.

## EDA, provenance, and drift harness

| Plan requirement | Result | Evidence |
| --- | --- | --- |
| Executed EDA for class balance | Passed | 2,260,701 rows scanned; resolved class counts and 19.965% default share persisted |
| Executed EDA for temporal composition | Passed | Quarterly volume/default tables and plots plus an executed notebook with six executed cells and no errors |
| Record versions, dates, licenses, and citations | Passed | Source registry, provenance policy, and acquisition manifest cover Kaggle Version 3 and UCI DOI `10.24432/C5NC77` with license caveats |
| Slice arbitrary feature-store time windows | Passed | Inclusive/exclusive UTC window contract implemented and tested across partitions |
| Apply optional rate and DTI perturbations | Passed | Absolute/relative, fractional, clipped, seeded perturbations implemented with audit manifests |
| Demonstrate deterministic drift output | Passed | Repeated real 2018Q4 run selected 5,030 rows and produced byte-identical Parquet and manifest hashes |

## Final verification gates

| Gate | Result |
| --- | --- |
| Acquisition rehash and structure validation | Passed for LendingClub and UCI German Credit |
| Real feature-store validation | Passed |
| Independent full production rebuild | Passed; all 94 Parquet files and the data dictionary are byte-identical |
| Real drift rerun | Passed; output and manifest are byte-identical |
| Train and backend transform parity | Passed on real fitted artifacts |
| Ruff | Passed |
| Pytest | Passed, 34 tests |
| Coverage | Passed, 86.01% against an enforced 85% floor |
| Dependency integrity | Passed with `pip check` |
| Wheel build | Passed |
| Docker build and launch | Passed on Docker Desktop 29.7.2 |
| Containerized feature-store workflow | Passed |
| Containerized drift workflow | Passed |

## Work deliberately outside Sprint 1

The plan assigns model training, class weights, LightGBM and logistic-regression
evaluation, SHAP, KS/ADWIN detection, FastAPI endpoints, authentication,
PostgreSQL/Redis, Docker Compose, React UI, Faker-backed applicant display,
deployment, human evaluation, and publication packaging to later sections.
Likewise, the acquired UCI data needs a separate adapter only when the
cross-dataset model evaluation is performed. None of these later deliverables
is silently represented as completed by this audit.
