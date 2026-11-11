"""SciCite loading and audit (3.1), on a miniature release in the real format.

Run from the repo root:  backend/.venv/bin/python -m pytest eval
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scicite import LABELS, audit, load, sample  # noqa: E402


def row(i, text, label, start="10", end="14", section="Introduction"):
    return {
        "string": text,
        "label": label,
        "citeStart": start,
        "citeEnd": end,
        "sectionName": section,
        "unique_id": f"u{i}",
        "citingPaperId": "a",
        "citedPaperId": "b",
    }


@pytest.fixture
def release(tmp_path):
    rows = {
        "train": [
            row(0, "We follow [12] for training.", "method", "10", "14"),
            row(1, "We follow [12] for training.", "method", "10", "14"),  # duplicate
            row(2, "Shared with dev, harmless.", "background", "nan", "nan"),
        ],
        "dev": [
            row(3, "Shared with dev, harmless.", "background", "0", "4", float("nan"))
        ],
        "test": [
            row(4, "Results match (Smith, 2019).", "result", "14", "27"),
            row(
                5, "Results match (Smith, 2019).", "background", "14", "27"
            ),  # conflict
            row(6, "", "method"),  # empty: skipped
            row(7, "Unknown label here [3].", "other"),  # bad label: skipped
            row(8, "Offsets point at the wrong words [4].", "background", "0", "7"),
        ],
    }
    for split, items in rows.items():
        (tmp_path / f"{split}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in items) + "\n"
        )
    return tmp_path


def test_splits_load_as_released_by_default(release):
    test = load("test", release)
    assert [e.id for e in test] == ["u4", "u5", "u8"]  # repeats kept; empty/bad skipped
    assert {e.label for e in test} <= set(LABELS)


def test_dedupe_drops_exact_repeats_keeping_the_first(release):
    assert [e.id for e in load("train", release, dedupe=True)] == ["u0", "u2"]


def test_a_nan_section_reads_as_none(release):
    (dev,) = load("dev", release)
    assert dev.section == ""


def test_unknown_split_is_refused(release):
    with pytest.raises(ValueError):
        load("validation", release)


def test_audit_counts_the_problems(release):
    report = audit(release)
    assert report["splits"]["train"]["duplicate_texts"] == 1
    assert report["splits"]["test"]["conflicting_labels"] == 1
    # NaN offsets and offsets landing on words without a number are suspect.
    assert report["splits"]["train"]["suspect_offsets"] == 1
    assert report["splits"]["test"]["suspect_offsets"] >= 1
    assert report["overlap"] == {"train_test": 0, "train_dev": 1, "dev_test": 0}


def test_sample_is_stratified_fixed_and_sized(release):
    pool = load("train", release) * 10
    first, again = sample(pool, 6, seed=3), sample(pool, 6, seed=3)
    assert first == again and len(first) <= 6
    assert {e.label for e in first} == {"method", "background"}
