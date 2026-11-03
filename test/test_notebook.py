# SPDX-License-Identifier: MIT
"""Runs docs/raw_data.ipynb on simulated data, so the guide keeps working with the library."""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbconvert.preprocessors import ExecutePreprocessor

NOTEBOOK = Path(__file__).parents[1] / "docs" / "raw_data.ipynb"


def test_raw_data_notebook_runs() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    ExecutePreprocessor(timeout=120).preprocess(notebook, {"metadata": {"path": str(NOTEBOOK.parent)}})
    text = "".join(out.get("text", "") for cell in notebook.cells for out in cell.get("outputs", []))
    assert "same as the steps above: True True" in text
