"""Server-owned reference data used to build the application wizard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ...core.rbac import PermissionCode
from ...core.security import require_permissions
from ...models.db_models import User
from ...models.schemas import (
    HOME_OWNERSHIP_VALUES,
    PURPOSE_VALUES,
    ApplicationSchemaResponse,
    ReferenceFieldResponse,
)

router = APIRouter(prefix="/reference", tags=["reference"])


def _field(
    name: str,
    label: str,
    field_type: str,
    group: str,
    description: str,
    *,
    required: bool = False,
    allowed_values: list[str | int] | None = None,
    format_hint: str | None = None,
    help_text: str | None = None,
) -> ReferenceFieldResponse:
    return ReferenceFieldResponse(
        name=name,
        label=label,
        type=field_type,
        group=group,
        required=required,
        nullable=not required,
        allowed_values=allowed_values,
        format=format_hint,
        help_text=help_text or description,
        description=description,
    )


APPLICATION_FIELDS = [
    _field(
        "annual_inc",
        "Annual income",
        "number",
        "Applicant & finances",
        "Gross annual income in USD.",
    ),
    _field(
        "dti",
        "Debt-to-income ratio",
        "number",
        "Applicant & finances",
        "Debt payments divided by income.",
    ),
    _field(
        "emp_length",
        "Employment length",
        "text",
        "Applicant & finances",
        "Years in employment, such as 5 years or 10+ years.",
    ),
    _field(
        "home_ownership",
        "Home ownership",
        "select",
        "Applicant & finances",
        "Current housing arrangement.",
        allowed_values=list(HOME_OWNERSHIP_VALUES),
    ),
    _field("loan_amnt", "Loan amount", "number", "Loan details", "Requested principal in USD."),
    _field(
        "term",
        "Term",
        "select",
        "Loan details",
        "Repayment term in months.",
        allowed_values=[36, 60],
    ),
    _field(
        "int_rate",
        "Interest rate",
        "number",
        "Loan details",
        "Annual interest rate as a number or percentage.",
    ),
    _field(
        "installment",
        "Monthly installment",
        "number",
        "Loan details",
        "Scheduled monthly payment in USD.",
    ),
    _field(
        "grade",
        "Grade",
        "select",
        "Loan details",
        "LendingClub credit grade.",
        allowed_values=list("ABCDEFG"),
    ),
    _field(
        "sub_grade",
        "Sub-grade",
        "select",
        "Loan details",
        "Grade plus band, from A1 through G5.",
        allowed_values=[f"{grade}{band}" for grade in "ABCDEFG" for band in range(1, 6)],
    ),
    _field(
        "purpose",
        "Loan purpose",
        "select",
        "Loan details",
        "Declared use of the loan proceeds.",
        allowed_values=list(PURPOSE_VALUES),
    ),
    _field(
        "issue_d",
        "Issue month",
        "month",
        "Loan details",
        "Month the loan is issued.",
        required=True,
        format_hint="Mon-YYYY, Mon-YY, or ISO date",
        help_text="Choose or enter the loan issue month.",
    ),
    _field(
        "revol_util",
        "Revolving utilization",
        "number",
        "Credit history",
        "Share of revolving credit currently used.",
    ),
    _field(
        "revol_bal",
        "Revolving balance",
        "number",
        "Credit history",
        "Outstanding revolving-credit balance in USD.",
    ),
    _field(
        "open_acc",
        "Open accounts",
        "number",
        "Credit history",
        "Number of currently open credit lines.",
    ),
    _field(
        "total_acc",
        "Total accounts",
        "number",
        "Credit history",
        "Total number of credit lines in the credit file.",
    ),
    _field(
        "delinq_2yrs",
        "Delinquencies in 2 years",
        "number",
        "Credit history",
        "Thirty-plus-day delinquencies in the past two years.",
    ),
    _field(
        "inq_last_6mths",
        "Inquiries in 6 months",
        "number",
        "Credit history",
        "Recent hard credit inquiries.",
    ),
    _field(
        "earliest_cr_line",
        "Earliest credit line",
        "month",
        "Credit history",
        "Month the oldest reported credit line opened.",
        format_hint="Mon-YYYY, Mon-YY, or ISO date",
    ),
]


@router.get("/application-schema", response_model=ApplicationSchemaResponse)
def application_schema(
    current_user: Annotated[
        User,
        Depends(require_permissions(PermissionCode.APPLICATION_CREATE)),
    ],
) -> ApplicationSchemaResponse:
    del current_user
    return ApplicationSchemaResponse(fields=APPLICATION_FIELDS)
