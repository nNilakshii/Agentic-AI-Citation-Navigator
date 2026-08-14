"""Citation-intent classification accuracy on SciCite (background / method / result).

Phase 3. Not runnable yet - depends on the agentic chat's intent classifier.

Contract:
    Input:  SciCite-labeled citances.
    Output: accuracy / macro-F1 over {background, method, result}.
"""


def evaluate(predictions: list[dict], gold: list[dict]) -> dict:
    """predictions / gold: [{"citance_id": str, "intent": str}, ...]
    Returns: {"accuracy": float, "macro_f1": float, "n": int}
    """
    raise NotImplementedError("Phase 3: implement once citation-intent classification exists.")


if __name__ == "__main__":
    raise SystemExit("Phase 3 stub - nothing to run yet. See CLAUDE.md build order.")
