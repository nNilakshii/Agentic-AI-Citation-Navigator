"""Cited-span localization accuracy on CL-SciSumm (WING-NUS scisumm-corpus).

Phase 2. Not runnable yet — the localizer it evaluates doesn't exist until Phase 2 lands.

Contract:
    Input:  gold citance -> cited-span annotations from CL-SciSumm.
    Output: localization accuracy, i.e. how often the predicted cited span overlaps
            the gold span (exact / partial match, configurable overlap threshold).
"""


def evaluate(predictions: list[dict], gold: list[dict]) -> dict:
    """Compare predicted cited spans against gold CL-SciSumm annotations.

    predictions / gold: [{"citance_id": str, "span_start": int, "span_end": int}, ...]
    Returns: {"exact_match": float, "overlap_match": float, "n": int}
    """
    raise NotImplementedError("Phase 2: implement once cited-span localization exists.")


if __name__ == "__main__":
    raise SystemExit("Phase 2 stub - nothing to run yet. See CLAUDE.md build order.")
