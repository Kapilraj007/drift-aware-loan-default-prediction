from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.execute_eda_notebook import execute_notebook

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "notebooks" / "01_eda_class_balance_temporal.ipynb"
DICTIONARY_PATH = ROOT / "docs" / "data_dictionary.csv"
REGISTRY_PATH = ROOT / "docs" / "source_registry.csv"
ACQUISITION_MANIFEST_PATH = ROOT / "data" / "raw" / "acquisition_manifest.csv"


def _load_notebook() -> dict:
    with NOTEBOOK_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def _notebook_source(notebook: dict) -> str:
    return "\n".join(
        "".join(cell.get("source", [])) for cell in notebook.get("cells", [])
    )


def test_eda_notebook_is_valid_unexecuted_nbformat_v4() -> None:
    notebook = _load_notebook()
    assert notebook["nbformat"] == 4
    assert notebook["cells"], "EDA notebook must contain documented analysis cells"

    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert code_cells
    assert all(cell.get("execution_count") is None for cell in code_cells)
    assert all(cell.get("outputs") == [] for cell in code_cells), (
        "Repository notebook must not cache empirical or placeholder findings"
    )


def test_eda_notebook_covers_config_target_and_quarter_contract() -> None:
    source = _notebook_source(_load_notebook())
    required_tokens = {
        "LOAN_DATA_PATH",
        "data/raw/accepted_loans.csv",
        "loan_status",
        "issue_d",
        "Charged Off",
        "Default",
        "Fully Paid",
        "to_period('Q')",
        "class_balance",
        "temporal_composition_by_quarter.csv",
        "default_rate",
        "EDA_HASH_INPUT",
    }
    missing = sorted(token for token in required_tokens if token not in source)
    assert not missing, f"EDA notebook is missing contract tokens: {missing}"


def test_data_dictionary_has_exact_sprint1_columns_and_required_fields() -> None:
    with DICTIONARY_PATH.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fieldnames = reader.fieldnames

    assert fieldnames == [
        "feature_name",
        "dtype",
        "source_column",
        "null_rate",
        "transformation_applied",
        "leakage_risk_flag",
    ]

    by_name = {row["feature_name"]: row for row in rows}
    expected_retained = {
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
        "purpose__*",
        "emp_length",
        "home_ownership__*",
        "loan_to_income",
        "credit_history_years",
        "installment_to_income",
    }
    assert expected_retained <= by_name.keys()

    for blocked in {"recoveries", "total_pymnt", "last_pymnt_d"}:
        assert by_name[blocked]["leakage_risk_flag"] == "true"
        assert by_name[blocked]["transformation_applied"].startswith("EXCLUDED_")

    assert by_name["loan_status"]["leakage_risk_flag"] == "true"
    assert by_name["issue_d"]["leakage_risk_flag"] == "true"
    assert all(row["null_rate"] == "" for row in rows), (
        "Static dictionary null rates must remain empty until computed from acquired bytes"
    )


def test_source_registry_links_completed_primary_and_secondary_acquisitions() -> None:
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with ACQUISITION_MANIFEST_PATH.open(encoding="utf-8", newline="") as stream:
        acquisition_rows = list(csv.DictReader(stream))

    by_id = {row["source_id"]: row for row in rows}
    acquisition_by_id = {row["source_id"]: row for row in acquisition_rows}
    assert "lendingclub_kaggle_v3" in by_id
    assert "uci_statlog_german_144" in by_id
    assert by_id["lendingclub_kaggle_v3"]["access_date_utc"]
    primary = by_id["lendingclub_kaggle_v3"]
    acquisition = acquisition_by_id["lendingclub_kaggle_v3"]
    assert primary["acquisition_date_utc"] == acquisition["acquisition_completed_utc"]
    assert primary["sha256"] == acquisition["archive_sha256"]
    assert primary["status"] == "acquired_verified"
    assert len(acquisition["pipeline_input_sha256"]) == 64
    secondary = by_id["uci_statlog_german_144"]
    secondary_acquisition = acquisition_by_id["uci_statlog_german_144"]
    assert secondary["acquisition_date_utc"] == secondary_acquisition[
        "acquisition_completed_utc"
    ]
    assert secondary["sha256"] == secondary_acquisition["pipeline_input_sha256"]
    assert secondary["status"] == "acquired_verified_benchmark_staged"
    assert secondary_acquisition["archive_size_bytes"] == "29607"
    assert secondary_acquisition["pipeline_input_size_bytes"] == "79793"
    assert "10.24432/C5NC77" in secondary["source_reported_version"]


def test_eda_notebook_executes_against_schema_compatible_sample(tmp_path: Path) -> None:
    data_path = tmp_path / "loans.csv"
    data_path.write_text(
        "export note before header\n"
        "loan_status,issue_d\n"
        "Fully Paid,Jan-2018\n"
        "Charged Off,Apr-2018\n"
        "default,Jul-2018\n"
        "Current,Oct-2018\n",
        encoding="utf-8",
    )
    output_directory = tmp_path / "eda"
    executed_path = execute_notebook(
        NOTEBOOK_PATH,
        tmp_path / "executed.ipynb",
        data_path=data_path,
        output_directory=output_directory,
        timeout=120,
    )

    executed = json.loads(executed_path.read_text(encoding="utf-8"))
    errors = [
        output
        for cell in executed["cells"]
        if cell["cell_type"] == "code"
        for output in cell.get("outputs", [])
        if output.get("output_type") == "error"
    ]
    assert errors == []
    metadata = json.loads(
        (output_directory / "eda_run_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["total_rows"] == 4
    assert metadata["resolved_rows"] == 3
    assert metadata["class_counts"] == {"0": 1, "1": 2}
    assert (output_directory / "class_balance.png").is_file()
    assert (output_directory / "temporal_composition.png").is_file()
