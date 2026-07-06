"""Generic utilities"""

from collections.abc import Iterator
from typing import Any


def tqdm_standin(iterator: "Iterator[Any]", *_: Any, **__: Any) -> "Iterator[Any]":
    """Alternative to tqdm, with no progress bar - ignore any arguments after the first"""
    return iterator
