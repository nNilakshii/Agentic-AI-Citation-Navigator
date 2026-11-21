"""How well the agent picks its tools (task 3.6).

Scores the model router and the keyword-rules fallback on the same
hand-labelled questions (``routing_questions.json``, written for this
project). Each question's gold is a *set* of tools; reported:

- **exact** — the predicted set equals the gold set;
- **first right** — the router's first tool is in the gold set (what the
  reader sees first);
- **per tool** — precision and recall for each tool.

The question set is small and was written before any router saw it; the
router prompt was not tuned on it, so it is scored once, as written.

    python eval/agent/run_routing_eval.py [--save]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.agent import ROUTER_VERSION, TOOLS, route, route_by_rules  # noqa: E402

QUESTIONS = HERE / "routing_questions.json"
CACHE = ROOT / "data" / "raw" / "agent-route-cache"


def score(predicted: list[list[str]], gold: list[list[str]]) -> dict:
    """Exact-set match, first-tool accuracy and per-tool P/R over paired lists."""
    if len(predicted) != len(gold):
        raise ValueError("one prediction per question")
    n = len(gold)
    per_tool = {}
    for tool in TOOLS:
        tp = sum(tool in p and tool in g for p, g in zip(predicted, gold))
        fp = sum(tool in p and tool not in g for p, g in zip(predicted, gold))
        fn = sum(tool not in p and tool in g for p, g in zip(predicted, gold))
        per_tool[tool] = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "gold": tp + fn,
        }
    return {
        "n": n,
        "exact": sum(set(p) == set(g) for p, g in zip(predicted, gold)) / n,
        "first_right": sum(bool(p) and p[0] in g for p, g in zip(predicted, gold)) / n,
        "per_tool": per_tool,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    from app.llm.client import GeminiClient

    data = json.loads(QUESTIONS.read_text())
    questions = [q["q"] for q in data["questions"]]
    gold = [q["tools"] for q in data["questions"]]
    llm = GeminiClient()

    async def all_llm():
        gate = asyncio.Semaphore(4)

        async def one(q):
            async with gate:
                return await route(q, llm, data["citance"], cache_dir=CACHE)

        return await asyncio.gather(*(one(q) for q in questions))

    llm_routes = asyncio.run(all_llm())
    fell_back = sum(r.by != "llm" for r in llm_routes)
    results = {
        "rules": score([route_by_rules(q).tools for q in questions], gold),
        "llm": score([r.tools for r in llm_routes], gold),
    }
    print(
        f"Routing — {len(questions)} hand-labelled questions, router v{ROUTER_VERSION}"
    )
    for name, r in results.items():
        label = f"{llm.model} router" if name == "llm" else "keyword rules"
        print(
            f"  {label:28} exact {r['exact']:.0%}   first tool right {r['first_right']:.0%}"
        )
        print(
            "    "
            + "  ".join(
                (
                    f"{t} P {v['precision']:.2f} R {v['recall']:.2f}"
                    if v["precision"] is not None
                    else f"{t} P –  R {v['recall']:.2f}"
                )
                for t, v in r["per_tool"].items()
            )
        )
    if fell_back:
        print(f"  INCOMPLETE: {fell_back} model routes fell back to the rules; re-run")
    misses = [
        (q, g, r.tools)
        for q, g, r in zip(questions, gold, llm_routes)
        if set(r.tools) != set(g)
    ]
    print(f"  model misses ({len(misses)}):")
    for q, g, p in misses:
        print(f"    {q!r}: gold {g}, routed {p}")

    if args.save:
        out = HERE / "results"
        out.mkdir(exist_ok=True)
        path = out / f"routing-{llm.model}-v{ROUTER_VERSION}.json"
        path.write_text(
            json.dumps(
                {
                    "model": llm.model,
                    "router_version": ROUTER_VERSION,
                    "fell_back": fell_back,
                    **results,
                    "model_misses": [
                        {"q": q, "gold": g, "routed": p} for q, g, p in misses
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        print(f"  saved {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
