"""The demonstration notebook should keep running as the library changes"""

import json
import os
from pathlib import Path

import pytest

NOTEBOOK = Path(__file__).parent.parent / "notebooks" / "snkit-demo.ipynb"


def test_demo_notebook_runs(tmp_path, monkeypatch):
    pytest.importorskip("matplotlib").use("Agg")
    pytest.importorskip("igraph")
    pytest.importorskip("networkx")
    cells = json.loads(NOTEBOOK.read_text())["cells"]
    code = ["".join(cell["source"]) for cell in cells if cell["cell_type"] == "code"]
    assert len(code) > 10
    # run where the notebook's data is, writing its output file elsewhere
    monkeypatch.chdir(NOTEBOOK.parent)
    namespace = {}
    for source in code:
        exec(source.replace('"network.gpkg"', repr(os.fspath(tmp_path / "network.gpkg"))), namespace)
    assert len(namespace["with_topology"].nodes) > 5
    assert namespace["path_nodes"][0] == "node_0"
