"""Generate a deterministic LendingClub-shaped CSV for smoke tests and demos.

The generated records are synthetic and must never be used to report research
metrics. They exist only to prove that the Sprint 1 pipeline works end to end
before the separately licensed source dataset is placed in ``data/raw``.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import date
from pathlib import Path

PURPOSES = ("debt_consolidation", "credit_card", "home_improvement", "small_business")
HOME_OWNERSHIP = ("RENT", "MORTGAGE", "OWN")
STATUSES = ("Fully Paid", "Charged Off", "Default", "Current", "In Grace Period")


def _month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%b-%Y")


def generate_rows(count: int, seed: int) -> list[dict[str, object]]:
    """Return deterministic, synthetic raw rows spanning multiple quarters."""

    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for index in range(count):
        quarter_index = index % 20
        year = 2014 + quarter_index // 4
        month = 1 + (quarter_index % 4) * 3
        trend = quarter_index / 19
        annual_inc = max(18_000, rng.gauss(72_000 - 8_000 * trend, 21_000))
        loan_amnt = rng.randrange(1_000, 35_001, 500)
        int_rate = max(5.0, min(31.0, rng.gauss(10.5 + 5.5 * trend, 3.1)))
        dti = max(0.0, min(45.0, rng.gauss(14.0 + 7.0 * trend, 7.0)))
        risk_logit = -3.0 + 0.07 * dti + 0.08 * int_rate + 0.000018 * loan_amnt
        default_probability = 1 / (1 + math.exp(-risk_logit))
        roll = rng.random()
        # Guarantee that every represented quarter contains both resolved
        # classes once it has at least two rows. This keeps the synthetic demo
        # deterministic and prevents expanding-window folds from failing by
        # chance, without changing any production training logic.
        quarter_cycle = index // 20
        if quarter_cycle == 0:
            status = "Fully Paid"
        elif quarter_cycle == 1:
            status = "Charged Off"
        elif index % 17 == 0:
            status = "Current"
        elif index % 29 == 0:
            status = "In Grace Period"
        elif roll < default_probability * 0.18:
            status = "Default"
        elif roll < default_probability:
            status = "Charged Off"
        else:
            status = "Fully Paid"

        earliest_year = rng.randint(1985, max(1986, year - 2))
        earliest_month = rng.randint(1, 12)
        grade_index = min(6, max(0, int((int_rate - 5) // 3.5)))
        grade = chr(ord("A") + grade_index)
        sub_grade = f"{grade}{rng.randint(1, 5)}"
        installment = loan_amnt * (1 + int_rate / 100) / (36 if rng.random() < 0.72 else 60)
        row: dict[str, object] = {
            "id": f"demo-{index + 1:06d}",
            "loan_status": status,
            "issue_d": _month_label(year, month),
            "earliest_cr_line": _month_label(earliest_year, earliest_month),
            "annual_inc": round(annual_inc, 2),
            "dti": round(dti, 2),
            "revol_util": f"{max(0.0, min(100.0, rng.gauss(48 + 10 * trend, 20))):.1f}%",
            "revol_bal": round(max(0.0, rng.gauss(14_000, 9_000)), 2),
            "open_acc": rng.randint(2, 24),
            "total_acc": rng.randint(5, 52),
            "delinq_2yrs": rng.choices([0, 1, 2, 3], weights=[82, 12, 4, 2])[0],
            "inq_last_6mths": rng.choices([0, 1, 2, 3, 4], weights=[38, 32, 18, 8, 4])[0],
            "loan_amnt": loan_amnt,
            "term": " 36 months" if installment > loan_amnt / 60 else " 60 months",
            "int_rate": f"{int_rate:.2f}%",
            "installment": round(installment, 2),
            "grade": grade,
            "sub_grade": sub_grade,
            "purpose": rng.choice(PURPOSES),
            "emp_length": rng.choice(
                ("< 1 year", "1 year", "2 years", "5 years", "10+ years", "n/a")
            ),
            "home_ownership": rng.choice(HOME_OWNERSHIP),
            # Deliberately present to prove the pipeline removes post-origination leakage.
            "recoveries": 0 if status == "Fully Paid" else round(rng.random() * 2_000, 2),
            "total_pymnt": round(rng.random() * loan_amnt, 2),
            "last_pymnt_d": _month_label(min(year + 2, 2020), month),
        }
        if index % 13 == 0:
            row["annual_inc"] = ""
        if index % 19 == 0:
            row["emp_length"] = ""
        rows.append(row)
    return rows


def write_demo_csv(output: Path, count: int, seed: int) -> Path:
    """Write demo rows and return the resolved output path."""

    if count < 20:
        raise ValueError("count must be at least 20 so every demo quarter is represented")
    rows = generate_rows(count=count, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/raw/demo_accepted_loans.csv"))
    parser.add_argument("--rows", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260926)
    args = parser.parse_args()
    path = write_demo_csv(args.output, args.rows, args.seed)
    print(f"Wrote {args.rows} synthetic rows to {path}")


if __name__ == "__main__":
    main()
