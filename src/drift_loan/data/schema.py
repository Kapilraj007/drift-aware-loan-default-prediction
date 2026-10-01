"""Canonical schema and leakage controls for LendingClub data.

Only columns in :data:`RAW_PREDICTOR_COLUMNS` are allowed to influence model
features.  Keeping this allow-list next to the explicit deny-list makes the
leakage boundary reviewable and prevents newly added CSV columns from silently
entering a model.
"""

from __future__ import annotations

from types import MappingProxyType

SCHEMA_VERSION = "1.0.0"

TARGET_SOURCE_COLUMN = "loan_status"
TARGET_COLUMN = "target"
ISSUE_DATE_COLUMN = "issue_d"
EARLIEST_CREDIT_COLUMN = "earliest_cr_line"
ISSUE_QUARTER_COLUMN = "issue_quarter"
SPLIT_COLUMN = "dataset_split"

RAW_NUMERIC_COLUMNS = (
    "annual_inc",
    "dti",
    "revol_util",
    "revol_bal",
    "open_acc",
    "total_acc",
    "delinq_2yrs",
    "inq_last_6mths",
    "loan_amnt",
    "term",
    "int_rate",
    "installment",
    "emp_length",
)

ENGINEERED_NUMERIC_COLUMNS = (
    "loan_to_income",
    "installment_to_income",
    "credit_history_years",
)

NUMERIC_FEATURE_COLUMNS = RAW_NUMERIC_COLUMNS + ENGINEERED_NUMERIC_COLUMNS
ORDINAL_COLUMNS = ("grade", "sub_grade")
ONE_HOT_COLUMNS = ("purpose", "home_ownership")

RAW_PREDICTOR_COLUMNS = (
    "annual_inc",
    "dti",
    "revol_util",
    "revol_bal",
    "open_acc",
    "total_acc",
    "delinq_2yrs",
    "inq_last_6mths",
    "loan_amnt",
    "term",
    "int_rate",
    "installment",
    "grade",
    "sub_grade",
    "purpose",
    "emp_length",
    "home_ownership",
    EARLIEST_CREDIT_COLUMN,
    ISSUE_DATE_COLUMN,
)

REQUIRED_INFERENCE_COLUMNS = frozenset(RAW_PREDICTOR_COLUMNS)
REQUIRED_TRAINING_COLUMNS = frozenset((*RAW_PREDICTOR_COLUMNS, TARGET_SOURCE_COLUMN))
INGESTION_ALLOWLIST = frozenset((*RAW_PREDICTOR_COLUMNS, TARGET_SOURCE_COLUMN))

# Outcome and post-origination fields observed across LendingClub releases.
# The transform is allow-list based, so this deny-list is a second, auditable
# guard rather than the sole protection against leakage.
LEAKAGE_COLUMNS = frozenset(
    {
        "collection_recovery_fee",
        "debt_settlement_flag",
        "debt_settlement_flag_date",
        "deferral_term",
        "hardship_amount",
        "hardship_dpd",
        "hardship_end_date",
        "hardship_flag",
        "hardship_last_payment_amount",
        "hardship_length",
        "hardship_loan_status",
        "hardship_payoff_balance_amount",
        "hardship_reason",
        "hardship_start_date",
        "hardship_status",
        "hardship_type",
        "last_credit_pull_d",
        "last_fico_range_high",
        "last_fico_range_low",
        "last_pymnt_amnt",
        "last_pymnt_d",
        "next_pymnt_d",
        "orig_projected_additional_accrued_interest",
        "out_prncp",
        "out_prncp_inv",
        "payment_plan_start_date",
        "pymnt_plan",
        "recoveries",
        "settlement_amount",
        "settlement_date",
        "settlement_percentage",
        "settlement_status",
        "settlement_term",
        "total_pymnt",
        "total_pymnt_inv",
        "total_rec_int",
        "total_rec_late_fee",
        "total_rec_prncp",
    }
)

DEFAULT_STATUSES = frozenset({"charged off", "default"})
NON_DEFAULT_STATUSES = frozenset({"fully paid"})
RESOLVED_STATUSES = DEFAULT_STATUSES | NON_DEFAULT_STATUSES

GRADE_TO_ORDINAL = MappingProxyType({letter: index for index, letter in enumerate("ABCDEFG")})
SUB_GRADE_TO_ORDINAL = MappingProxyType(
    {
        f"{letter}{number}": grade_index * 5 + number - 1
        for grade_index, letter in enumerate("ABCDEFG")
        for number in range(1, 6)
    }
)

MISSING_CATEGORY = "__MISSING__"
UNKNOWN_ORDINAL_VALUE = -1


def missing_flag_name(feature_name: str) -> str:
    """Return the stable missingness-indicator name for a numeric feature."""

    return f"{feature_name}_was_missing"
