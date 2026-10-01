"""Execute the Sprint 1 EDA notebook with an explicit input and output path."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient


def execute_notebook(
    notebook_path: Path,
    output_notebook: Path,
    *,
    data_path: Path,
    output_directory: Path,
    timeout: int,
) -> Path:
    notebook_path = notebook_path.expanduser().resolve()
    data_path = data_path.expanduser().resolve()
    output_notebook = output_notebook.expanduser().resolve()
    output_directory = output_directory.expanduser().resolve()
    if not notebook_path.is_file():
        raise FileNotFoundError(f"EDA notebook not found: {notebook_path}")
    if not data_path.is_file():
        raise FileNotFoundError(f"EDA input CSV not found: {data_path}")

    notebook = nbformat.read(notebook_path, as_version=4)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    runtime_root = output_directory / ".runtime"
    runtime_environment = {
        "IPYTHONDIR": runtime_root / "ipython",
        "JUPYTER_CONFIG_DIR": runtime_root / "jupyter_config",
        "JUPYTER_DATA_DIR": runtime_root / "jupyter_data",
        "JUPYTER_RUNTIME_DIR": runtime_root / "jupyter_runtime",
        "MPLCONFIGDIR": runtime_root / "matplotlib",
    }
    for directory in runtime_environment.values():
        directory.mkdir(parents=True, exist_ok=True)
    previous = {
        name: os.environ.get(name)
        for name in (
            "LOAN_DATA_PATH",
            "EDA_OUTPUT_DIR",
            "EDA_HASH_INPUT",
            *runtime_environment,
        )
    }
    os.environ["LOAN_DATA_PATH"] = str(data_path)
    os.environ["EDA_OUTPUT_DIR"] = str(output_directory)
    os.environ["EDA_HASH_INPUT"] = "1"
    for name, directory in runtime_environment.items():
        os.environ[name] = str(directory)
    try:
        client = NotebookClient(
            notebook,
            timeout=timeout,
            kernel_name="python3",
            resources={"metadata": {"path": str(notebook_path.parent.parent)}},
        )
        client.execute()
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(runtime_root, ignore_errors=True)

    output_notebook.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, output_notebook)
    return output_notebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--notebook",
        type=Path,
        default=Path("notebooks/01_eda_class_balance_temporal.ipynb"),
    )
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--output-notebook",
        type=Path,
        default=Path("reports/generated/01_eda_executed.ipynb"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/generated/eda"),
    )
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    output = execute_notebook(
        args.notebook,
        args.output_notebook,
        data_path=args.data,
        output_directory=args.output_dir,
        timeout=args.timeout,
    )
    print(f"Executed notebook written to {output}")


if __name__ == "__main__":
    main()
