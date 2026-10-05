# Sprint 1 completion report

> Historical note: the container-based topology described in this report was
> removed in Phase 2; current setup and verification commands are in the root README.

## Status

Sprint 1 is complete against the real LendingClub accepted-loan dataset. The
primary source was downloaded, preserved, checksummed, analyzed, transformed,
validated, and exercised through the drift harness. Synthetic data remains only
as a fast test fixture. The default UCI German Credit secondary benchmark is
also downloaded, checksummed, and staged for the later cross-dataset model
evaluation.

## Acquisition identity

| Item | Value |
| --- | --- |
| Source | Kaggle `wordsforthewise/lending-club`, Version 3 |
| License reported by Kaggle | CC0-1.0 |
| Acquisition completed | 2026-09-27T15:46:25.0011321Z |
| Archive | `accepted_2007_to_2018Q4.csv.gz` |
| Archive bytes | 392,582,231 |
| Archive SHA-256 | `55c16f75120f897683f02e7aabcf080d0e4a20c4832feb1d592cfa941bd62a2d` |
| Pipeline input | `accepted_loans.csv` |
| Pipeline-input bytes | 1,675,133,810 |
| Pipeline-input SHA-256 | `3eae03c28fd9d2e8a076ebeb73507e8d4d0f44d90500decdb0936e0933d1f36a` |

The complete machine-readable record is
[`../data/raw/acquisition_manifest.csv`](../data/raw/acquisition_manifest.csv).
Raw row-level files remain excluded from version control.

The official UCI German Credit ZIP is 29,607 bytes with SHA-256
`e12d9d5def6845c0622634a1cd2ab87fa470668c4298f1ec52a4e403376a435b`.
Its selected `german.data` input is 79,793 bytes with SHA-256
`b21f3d81db8071257d5ff1deaeba1fd4303b62712e6fcc9715c7a86202cb5871`.
Validation confirmed 1,000 rows, 20 predictors plus the target, no missing
fields, and the documented 700/300 class split. It is intentionally not mixed
with the LendingClub feature store because its schema and outcome differ.

## Real-data EDA

The executed notebook scanned 2,260,701 rows and found 1,345,350 outcomes that
match the target contract:

| Target | Meaning | Rows | Share |
| --- | --- | ---: | ---: |
| 0 | Fully Paid | 1,076,751 | 80.0350% |
| 1 | Charged Off or Default | 268,599 | 19.9650% |

The run excluded 915,351 unresolved or unmapped rows and found zero retained
rows with an invalid `issue_d`. It produced class-balance and quarterly
composition CSVs and PNGs, an input-hash metadata record, and an executed
notebook with six executed code cells and zero error outputs.

## Feature-store result

The bounded-memory production build generated 53 model features and 47 complete
quarter partitions from 2007Q2 through 2018Q4 in both unscaled and scaled views.

| Split | Quarters | Rows |
| --- | --- | ---: |
| Train | 2007Q2-2014Q1 | 274,970 |
| Validation | 2014Q2-2016Q2 | 726,519 |
| Shift holdout | 2016Q3-2018Q4 | 343,861 |

The fitted transformer and scaler were learned only from the training quarters.
The internal and external artifact copies have matching hashes. A real raw row
transformed through the backend-facing import produced the same 53-feature
schema with finite scaled and unscaled values.

## Quality gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Acquisition metadata and hashes | Passed | Acquisition manifest matches the build source hash and size |
| Required columns and duplicate rejection | Passed | Ingestion validation and automated tests |
| Target mapping and excluded-status counts | Passed | EDA metadata and feature-store manifest |
| Valid canonical issue quarters | Passed | 47 chronological partitions; zero invalid retained dates |
| No NaN or infinite model values | Passed | Partition-by-partition validator |
| Deterministic schema and order | Passed | Full rerun matched 20 stable manifest fields |
| No leakage fields in model matrix | Passed | Empty leakage-feature intersection |
| Chronological partitions and splits | Passed | Quarter inventory and `quarter_to_split` validation |
| Reproducible outputs | Passed | Full rerun produced byte-identical data dictionary and all 94 Parquet files |
| Docker image build and launch | Passed | Image built, CLI launched, feature store and drift run completed in containers |

The full-build comparison hashes are:

- unscaled inventory: `b4fabbd74ffe10c9d74a551714d8529338945619ee48ff95b0e1f5a4f2c4cb5b`
- scaled inventory: `0dec6e4bab956daba2e1cf9a336c384eeb76f0feb29b4d56e3f572f27051abed`

## Drift-harness verification

A seeded 2018Q4 window selected 5,030 real holdout rows. The run applied a
1.5-point absolute `int_rate` shift and a 10% relative `dti` shift without
modifying protected metadata or targets. Repeating the run produced identical
outputs:

- Parquet SHA-256: `8f10d1400ea6ece76f7549cc3b10b374841547468fdc100c6546c1cc2a1b337f`
- manifest SHA-256: `002566516689af16494a2e3ed4d9e8774ca42022d25c3a8ab38e76a1ab61d297`

## Docker verification

Docker Desktop 29.7.2 was started and the repository Dockerfile was built as
`drift-loan-sprint1:verified`. The retained image's exact creation time, size,
ID, and digest were recorded in the generated evidence set available at the time.
Launching it with `--version` returned `drift-loan 0.1.0`.

A mounted 400-row synthetic fixture then exercised the packaged build command
inside the container. It produced 363 resolved rows, 41 fixture-observed
features, 20 quarterly partitions, fitted artifacts, and chronological split
counts of 219 train, 73 validation, and 71 shift rows. A second container run
sliced the 71-row 2018 shift window and applied seeded interest-rate and DTI
perturbations successfully.

## Verification summary

- Ruff: passed.
- Pytest: 34 passed.
- Coverage: 86.01%, above the enforced 85% threshold.
- Dependency integrity: `pip check` passed.
- Wheel: built successfully; it contains the streaming module.
- Feature-store validator: passed all checks.
- Full-build reproducibility comparison: passed.
- Acquisition validator: passed both downloaded sources, sizes, hashes, and
  structural checks.
- Docker build, CLI launch, containerized feature-store build, and containerized
  drift simulation: passed.

## Local evidence

- `data/processed/feature_store/manifest.json`
- `data/processed/feature_store/data_dictionary.csv`
- `data/artifacts/preprocessor/`
- `reports/generated/01_eda_executed.ipynb`
- `reports/generated/eda/`
- `reports/generated/feature_store_validation.json`
- `reports/generated/feature_store_reproducibility.json`
- `reports/generated/acquisition_validation.json`
- `reports/generated/drift/`

The selected UCI German Credit bytes are acquired and provenance-verified. Its
adapter and cross-dataset model run remain later-sprint evaluation work, so the
benchmark is not an input to the Sprint 1 LendingClub pipeline.
