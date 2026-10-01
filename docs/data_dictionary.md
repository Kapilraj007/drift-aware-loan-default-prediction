# LendingClub Sprint 1 data dictionary

## Scope

[`data_dictionary.csv`](data_dictionary.csv) is the baseline logical schema for
the primary LendingClub pipeline. It contains exactly the Sprint 1 columns:

`feature_name`, `dtype`, `source_column`, `null_rate`,
`transformation_applied`, and `leakage_risk_flag`.

The dictionary includes retained raw features, engineered features, missingness
indicators, target/partition helper fields, and a minimum explicit leakage
denylist. The implementation must use an allowlist for model features, so an
unlisted raw column cannot enter the model merely because it was present in a
new source file.

## Column semantics

- **feature_name:** logical output name. `purpose_*` and
  `home_ownership_*` represent the family of one-hot columns whose concrete
  categories are learned from the training window only.
- **dtype:** expected post-transform logical type.
- **source_column:** raw source column or pipe-delimited inputs for a derived
  value.
- **null_rate:** empty in the static template. The ingest run computes
  `null_count / row_count` on raw values before imputation and writes a
  versioned run dictionary. An empty template value must never be interpreted
  as zero.
- **transformation_applied:** deterministic transformation and artifact role.
- **leakage_risk_flag:** `true` means the field is forbidden from the model
  matrix. `false` means it is eligible only through the named transformation.

## Target and temporal rules

The binary target is derived only from resolved statuses:

| Raw `loan_status` | Target |
|---|---:|
| `Charged Off` | 1 |
| `Default` | 1 |
| `Fully Paid` | 0 |

Every other status is excluded and reported. It is not mapped to the
non-default class. `issue_d` defines quarter partitions and chronological
splits but is never passed to a model. `earliest_cr_line` is used only to derive
`credit_history_years` relative to `issue_d`.

## Missing values and fitting boundaries

Numeric medians, ordinal mappings, scaling parameters, and one-hot categories
are fit on the training window only. Validation and held-out shift windows use
those frozen parameters. Missingness indicators reflect the value before
imputation. Safe ratio calculations treat a missing or non-positive denominator
as missing before imputation instead of emitting infinity.

The tree-model view does not require scaling. A separately fitted
StandardScaler view may be materialized for Sprint 2 logistic regression; it
must be derived from the same transformed feature contract and training window.

## Leakage controls

The explicit blocked rows include the examples named in the project plan
(`recoveries`, `total_pymnt`, and `last_pymnt_d`) and related post-origination
payment, recovery, outstanding-principal, hardship, settlement, and later FICO
fields. This list is defense in depth. The authoritative control is the positive
feature allowlist, accompanied by an assertion that no blocked field appears in
the model matrix.

Loan amount, term, interest rate, installment, grade, and sub-grade are retained
because the Sprint 1 specification treats them as information available at the
origination decision point. If a deployment scores applications before those
terms are assigned, the availability contract must be revised before claiming
pre-origination performance.

## Run-time dictionary production

Each successful feature-store build writes `data_dictionary.csv` beside the
store manifest. It expands one-hot families into their concrete fitted output
columns and populates pre-imputation null rates over resolved rows. Numeric and
engineered rates come from the matching `*_was_missing` indicators; categorical
rates come from the resolved raw inputs. The manifest records SHA-256 digests
for both the generated dictionary and fitted preprocessing artifacts. No
empirical rates are committed in this static template because no source
artifact is bundled with the repository.
