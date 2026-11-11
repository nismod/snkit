"""Run the conformance cases, and check that what is generated from them is up to date.

The cases are data files in ``conformance/``; see ``conformance/README.md``.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "conformance"))

import generate  # noqa: E402
import run  # noqa: E402

CASES = run.load_cases()


def make_examples():
    spec = importlib.util.spec_from_file_location("make_examples", ROOT / "docs" / "make_examples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_there_are_cases_of_both_tiers():
    assert any(name.startswith("operations/") for name in CASES)
    assert any(name.startswith("kernel/") for name in CASES)


@pytest.mark.parametrize("name", list(CASES))
def test_case(name):
    case = CASES[name]
    problems = run.compare(run.run_case(case), case["expected"])
    assert not problems, "\n".join(problems)


def test_every_kernel_function_has_cases():
    covered = {case["function"] for name, case in CASES.items() if name.startswith("kernel/")}
    assert covered == set(run.KERNEL_OUTPUTS)


def test_case_files_are_what_generate_writes():
    assert set(CASES) == set(generate.CASES)
    for name, definition in generate.CASES.items():
        text = (run.ROOT / f"{name}.json").read_text(encoding="utf-8")
        assert text == generate.dumps(generate.build(name, definition)) + "\n", name


def test_compare_notices_differences():
    expected = {"nodes": [{"id": 0, "geometry": "POINT (0 0)", "name": None}], "edges": []}
    same = {"nodes": [{"id": 0, "geometry": "POINT (0.0 1e-12)"}], "edges": []}
    assert run.compare(same, expected) == []
    for other in (
        {"nodes": [{"id": 1, "geometry": "POINT (0 0)"}], "edges": []},
        {"nodes": [{"id": 0, "geometry": "POINT (0 0.001)"}], "edges": []},
        {"nodes": [{"id": 0, "geometry": "POINT (0 0)", "name": "a"}], "edges": []},
        {"nodes": [], "edges": []},
        {"error": True, "message": "refused"},
    ):
        assert run.compare(other, expected)
    assert run.compare({"error": True, "message": "refused"}, {"error": True}) == []
    assert run.compare(expected, {"error": True})


def test_examples_page_is_up_to_date():
    examples = make_examples()
    cases = examples.ordered_cases()
    page = examples.PAGE.read_text(encoding="utf-8")
    assert page == examples.render_page(cases), "run `python docs/make_examples.py`"


def test_example_figures_are_up_to_date():
    examples = make_examples()
    cases = examples.ordered_cases()
    images = sorted(path.name for path in examples.IMAGES.glob("*.svg"))
    assert images == examples.image_names(cases), "run `python docs/make_examples.py`"
