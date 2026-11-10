"""Run the examples in docstrings as tests"""

import doctest

import pytest

import snkit.arrays
import snkit.core
import snkit.match
import snkit.multi
import snkit.operations
import snkit.tiled


@pytest.mark.parametrize(
    "module",
    [snkit.arrays, snkit.core, snkit.match, snkit.multi, snkit.operations, snkit.tiled],
    ids=lambda m: m.__name__,
)
def test_docstring_examples(module):
    result = doctest.testmod(module, optionflags=doctest.NORMALIZE_WHITESPACE)
    assert result.attempted > 0
    assert result.failed == 0
