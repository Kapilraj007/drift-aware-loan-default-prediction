from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from drift_loan.cli import build_parser, main


def test_cli_parser_exposes_complete_sprint_one_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "build" in help_text
    assert "simulate-drift" in help_text


def test_simulate_drift_cli_writes_data_and_manifest(
    tmp_path: Path,
    capsys: object,
) -> None:
    store = tmp_path / "feature_store"
    frame = pd.DataFrame(
        {
            "issue_d": pd.to_datetime(["2018-01-01", "2018-04-01"]),
            "issue_quarter": ["2018Q1", "2018Q2"],
            "dataset_split": ["validation", "shift"],
            "target": [0, 1],
            "int_rate": [10.0, 20.0],
            "dti": [15.0, 25.0],
        }
    )
    frame.to_parquet(store / "unscaled", partition_cols=["issue_quarter"], index=False)
    output = tmp_path / "simulated.parquet"

    exit_code = main(
        [
            "simulate-drift",
            str(store),
            "--output",
            str(output),
            "--int-rate-shift",
            "0.15",
            "--int-rate-mode",
            "relative",
            "--seed",
            "17",
        ]
    )

    assert exit_code == 0
    assert output.is_file()
    manifest = output.with_suffix(".manifest.json")
    assert manifest.is_file()
    shifted = pd.read_parquet(output)
    assert shifted["int_rate"].tolist() == [11.5, 23.0]
    summary = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert summary["rows_selected"] == 2
    assert summary["seed"] == 17

