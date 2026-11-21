"""Routing scores (3.6): sets compared, order only for the first tool."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_routing_eval import score  # noqa: E402


def test_exact_ignores_order_but_first_right_does_not():
    r = score([["impact", "intent"], ["locate"]], [["intent", "impact"], ["evidence"]])
    assert r["exact"] == 0.5 and r["first_right"] == 0.5


def test_per_tool_precision_and_recall():
    r = score(
        [["evidence"], ["evidence"], ["impact"]], [["evidence"], ["impact"], ["impact"]]
    )
    assert r["per_tool"]["evidence"]["precision"] == 0.5
    assert r["per_tool"]["impact"]["recall"] == 0.5
    assert r["per_tool"]["locate"]["precision"] is None


def test_lengths_must_match():
    with pytest.raises(ValueError):
        score([["evidence"]], [])
