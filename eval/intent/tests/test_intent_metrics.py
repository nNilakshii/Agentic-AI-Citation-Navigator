"""SciCite scoring (3.2): macro-F1, with invalid replies counted as wrong."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_scicite_eval import evaluate  # noqa: E402


def rows(labels):
    return [{"citance_id": str(i), "intent": l} for i, l in enumerate(labels)]


def test_perfect_predictions():
    gold = rows(["background", "method", "result"])
    r = evaluate(gold, gold)
    assert r["macro_f1"] == 1.0 and r["accuracy"] == 1.0 and r["invalid"] == 0


def test_macro_f1_weighs_each_class_equally():
    gold = rows(["background"] * 8 + ["method", "result"])
    pred = rows(["background"] * 10)  # majority class only
    r = evaluate(pred, gold)
    assert r["accuracy"] == 0.8
    bg = r["per_class"]["background"]
    assert bg["precision"] == 0.8 and bg["recall"] == 1.0
    assert r["per_class"]["method"]["f1"] == 0.0
    assert r["macro_f1"] == pytest.approx((2 * 0.8 / 1.8) / 3)


def test_an_invalid_reply_is_wrong_and_no_class_gains_a_positive():
    gold = rows(["method", "result"])
    pred = rows([None, "result"])
    r = evaluate(pred, gold)
    assert r["invalid"] == 1 and r["accuracy"] == 0.5
    assert r["per_class"]["method"]["recall"] == 0.0
    assert r["per_class"]["result"]["precision"] == 1.0
    assert r["confusion"]["method"]["invalid"] == 1


def test_every_gold_id_needs_a_prediction():
    with pytest.raises(ValueError):
        evaluate(rows(["method"]), rows(["method", "result"]))
