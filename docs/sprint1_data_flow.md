# Sprint 1 data flow and artifact contract

## System boundary

The Sprint 1 pipeline turns an immutable, locally acquired accepted-loan CSV
into a leakage-controlled Parquet feature store partitioned by issue quarter.
EDA, temporal splitting, drift simulation, Sprint 2 training, and later
inference all consume the same transformation contract. Notebook-only feature
logic is prohibited.

```text
authenticated source
        |
        v
immutable raw artifact + acquisition manifest + SHA-256
        |
        v
schema validation and resolved-outcome filtering
        |
        v
shared deterministic feature transformation
        |
        +--> run data dictionary and quality manifest
        |
        v
Parquet feature store with scaled and unscaled views partitioned by issue quarter
        |
        +--> EDA: class balance and quarter composition
        +--> chronological train / validation / held-out shift windows
        +--> drift-window slicer and optional seeded perturbations
```

## Stage contracts

### Acquisition

Input bytes remain in `data/raw/`, are excluded from version control, and are
identified by the fields in [`source_registry.csv`](source_registry.csv). A
file without a completed local acquisition manifest is unversioned input and
must not back a reported experiment.

### Validation and target construction

The pipeline validates the required allowlisted columns before transformation.
It inventories every `loan_status`, maps only the three specified resolved
statuses, and writes counts for retained and excluded rows. It parses `issue_d`
and reports invalid/missing dates. A run must fail clearly if no resolved rows
or no valid temporal rows remain.

### Feature transformation

Raw parsing and deterministic feature engineering are shared library code.
Fitted state - medians, category mappings, one-hot categories, and any scaler -
is learned only from the training window and serialized with the feature order.
Validation, shift tests, and API inference reuse that state.

The model matrix is produced from an explicit allowlist. After construction, a
leakage assertion checks that no `leakage_risk_flag=true` field from the data
dictionary is present. Ratios use guarded division, and non-finite values are
converted to missing before imputation.

### Feature store

The feature store root is `data/processed/feature_store`. Its `unscaled/` and
`scaled/` variants are each partitioned as
`issue_quarter=YYYYQn/part-00000.parquet`, with `manifest.json` and a fitted
artifact copy under `artifacts/`. The configured external artifact directory is
`data/artifacts/preprocessor`. Partition values sort chronologically and are
metadata, not model features. Metadata stored next to the feature store includes:

- each source path, byte size, and SHA-256 digest;
- transform schema version and run configuration;
- row counts before and after resolved-status filtering;
- the complete status inventory and excluded-row count;
- temporal split fractions, quarter boundaries, and row counts;
- output feature names and dtypes;
- fitted-artifact and run-data-dictionary SHA-256 digests; and
- minimum and maximum retained issue quarter.

The separate acquisition manifest links those bytes to the source registry,
authenticated download timestamp, license review, and later repository release
or commit. A code revision is recorded at experiment publication time rather
than invented when the working tree has no commit.

Writing should be atomic: materialize to a run-specific temporary destination,
validate expected partitions and schema, then promote the completed artifact.

### Time split

Split boundaries are quarter labels, not row proportions. Training contains the
earliest contiguous quarters; validation contains the next contiguous block;
the held-out shift set contains the latest block. Boundaries are recorded in
experiment metadata. No random shuffle may move a later loan into an earlier
fit window.

### EDA

[`../notebooks/01_eda_class_balance_temporal.ipynb`](../notebooks/01_eda_class_balance_temporal.ipynb)
streams only `loan_status` and `issue_d` from a configured CSV. It reports
status exclusions, resolved class balance, and quarterly resolved volume and
default rate. The notebook contains no cached empirical outputs; tables and
figures are generated only from the configured bytes.

### Drift simulation

The drift harness consumes feature-store quarters through the same chronological
labels. A synthetic perturbation must be explicit, seeded, non-destructive, and
return metadata identifying the feature, operation, magnitude, seed, and rows
affected. Synthetic variants never overwrite the real partition.

## Quality gates

A Sprint 1 data run is accepted only when all of the following hold:

1. acquisition metadata and SHA-256 are complete;
2. required raw columns exist and duplicate column names are rejected;
3. target mapping counts and excluded-status counts are recorded;
4. all retained temporal rows have a valid canonical quarter;
5. output rows contain no NaN or infinite model values after transformation;
6. output schema/order are deterministic for the same fit artifact;
7. leakage denylist intersection with the model matrix is empty;
8. Parquet partitions and split boundaries are chronological; and
9. a rerun from the same bytes, configuration, seed, and code revision produces
   the same schema, counts, and deterministic perturbation output.

## Verified local reference run

The 2026-09-27 UTC LendingClub acquisition has passed all nine gates. The build
scanned 2,260,701 rows, retained 1,345,350 resolved outcomes, produced 53 model
features across 47 quarters (2007Q2-2018Q4), and recorded 274,970 train,
726,519 validation, and 343,861 shift rows. Partition validation found no NaN or
infinite model values and no leakage-column intersection. A seeded 2018Q4 drift
run selected 5,030 rows; its repeated Parquet and manifest outputs were
byte-identical. A second full build also produced identical stable metadata,
data dictionary, and all 94 Parquet files. Local evidence is written to
`reports/generated/feature_store_validation.json` and
`reports/generated/feature_store_reproducibility.json`, with drift evidence
under `reports/generated/drift/`.
