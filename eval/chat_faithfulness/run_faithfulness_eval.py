"""RAGAS-style faithfulness/groundedness eval for the agentic citation chat.

Phase 3. Not runnable yet - depends on the chat's RAG pipeline over cited papers.

Contract:
    Input:  chat answers + the retrieved source spans they were grounded in.
    Output: faithfulness score (does every claim trace back to a retrieved span?).
"""


def evaluate(answers: list[dict]) -> dict:
    """answers: [{"question": str, "answer": str, "retrieved_spans": list[str]}, ...]
    Returns: {"faithfulness": float, "n": int}
    """
    raise NotImplementedError("Phase 3: implement once the agentic chat exists.")


if __name__ == "__main__":
    raise SystemExit("Phase 3 stub - nothing to run yet. See docs/TASKS.md for the build order.")
