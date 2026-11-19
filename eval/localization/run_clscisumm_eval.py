"""Evaluate cited-span localization on CL-SciSumm Task 1A (task 2.6).

For every human-annotated citance: rebuild the reference paper from the
corpus's own sentences, cut it into candidate passages exactly as the app does
(2.4), rank them for the citance exactly as the app does (2.5), and score the
ranking against the gold sentences.

Besides the metrics, it reports two numbers that keep the others honest:

- **Candidate coverage** — how often the gold sentences survive 2.4's
  exclusions at all. A gold sentence that was filtered out can never be found,
  so this is the ceiling on recall.
- **A random ranking**, the floor: what the metrics look like by chance.

The corpus must be cloned first (see ``clscisumm.py``). Embeddings are cached
under ``data/cache/embeddings/``, so re-runs are fast.

    python eval/localization/run_clscisumm_eval.py                  # all 753
    python eval/localization/run_clscisumm_eval.py --split dev      # tuning set
    python eval/localization/run_clscisumm_eval.py --ranker random
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "backend")]

import numpy as np  # noqa: E402

from app.core.embedding import DEFAULT_MODEL  # noqa: E402
from app.core.localizer import LOCALIZER_VERSION, select_top  # noqa: E402
from app.core.llm_localizer import POOL  # noqa: E402
from app.core.passages import PASSAGE_VERSION, passages_from_paper  # noqa: E402
from clscisumm import (
    CORPUS,
    load_citances,
    load_reference,
    papers,
    split_of,
)  # noqa: E402
from rankers import (
    bm25_scores,
    embedding_scores,
    hybrid_scores,
    make_embedder,
)  # noqa: E402
from metrics import Counts, averaged_over_papers, hit_at_k, rouge_l  # noqa: E402

KS = (1, 3, 5, 10)
RESULTS = HERE / "results"


def evaluate(
    split: str,
    ranker: str,
    model: str,
    seed: int = 0,
    max_window: int = 3,
    alpha: float = 0.5,
    reranker=None,
    max_papers: int | None = None,
    pool: int = POOL,
) -> dict:
    """Score one ranker on one split.

    ``reranker``, if given, is called once per paper with the citances, the
    paper and each citance's ranked shortlist (``POOL`` long), and returns the
    lists re-ordered — how 2.8's LLM is evaluated on exactly 2.7's candidates.
    """
    embedder = make_embedder(model) if ranker in ("embedding", "hybrid") else None
    rng = random.Random(seed)
    per_paper: dict[str, Counts] = {}
    pooled = Counts()
    hits = {k: 0 for k in KS}
    rouge, n = 0.0, 0
    covered_all = covered_any = 0
    by_facet: dict[str, list[int]] = {}
    rows = []

    seen_papers = 0
    for paper in papers():
        if split != "all" and split_of(paper) != split:
            continue
        if max_papers is not None and seen_papers >= max_papers:
            break
        seen_papers += 1
        citances = load_citances(paper)
        if not citances:
            continue
        reference = load_reference(paper)
        text_of = {s.id: s.text for s in reference.sentences}
        passages = [
            p
            for p in passages_from_paper(reference).passages
            if len(p.sentence_ids) <= max_window
        ]
        candidates = {i for p in passages for i in p.sentence_ids}

        texts, queries = [p.text for p in passages], [c.query for c in citances]
        if ranker == "embedding":
            all_scores = embedding_scores(embedder, texts, queries)
        elif ranker == "bm25":
            all_scores = bm25_scores(texts, queries)
        elif ranker == "hybrid":
            all_scores = hybrid_scores(
                bm25_scores(texts, queries),
                embedding_scores(embedder, texts, queries),
                alpha,
            )
        else:
            all_scores = np.array([[rng.random() for _ in passages] for _ in citances])

        counts = per_paper.setdefault(paper, Counts())
        shortlists = [
            select_top(passages, scores, pool if reranker else max(KS))
            for scores in all_scores
        ]
        extras = [{} for _ in citances]
        if reranker:
            shortlists, extras = reranker(citances, reference, shortlists)
        for citance, ranked, extra in zip(citances, shortlists, extras):
            ranked_sets = [set(r.passage.sentence_ids) for r in ranked]
            gold = set(citance.gold)
            top = ranked_sets[0] if ranked_sets else set()

            counts.add(top, gold)
            pooled.add(top, gold)
            for k in KS:
                hits[k] += hit_at_k(ranked_sets, gold, k)
            rouge += rouge_l(
                ranked[0].passage.text if ranked else "",
                " ".join(text_of[i] for i in sorted(gold, key=int) if i in text_of),
            )
            covered_all += gold <= candidates
            covered_any += bool(gold & candidates)
            for facet in citance.facets:
                by_facet.setdefault(facet, []).append(hit_at_k(ranked_sets, gold, 1))
            n += 1
            rows.append(
                {
                    "citance": citance.key,
                    "split": split_of(paper),
                    "query": citance.query,
                    "gold": sorted(gold, key=int),
                    "top": [
                        {"sentences": r.passage.sentence_ids, "score": r.score}
                        for r in ranked[:5]
                    ],
                    "hit_at_1": hit_at_k(ranked_sets, gold, 1),
                    "gold_in_candidates": gold <= candidates,
                    **extra,
                }
            )

    p, r, f = averaged_over_papers(per_paper.values())
    pp, pr, pf = pooled.prf()
    return {
        "split": split,
        "ranker": ranker,
        "model": model if ranker in ("embedding", "hybrid") else None,
        "max_window": max_window,
        "alpha": alpha if ranker == "hybrid" else None,
        "passage_version": PASSAGE_VERSION,
        "localizer_version": LOCALIZER_VERSION,
        "papers": len(per_paper),
        "citances": n,
        "sentence_overlap": {"precision": p, "recall": r, "f1": f},
        "sentence_overlap_pooled": {"precision": pp, "recall": pr, "f1": pf},
        "rouge_l_f1": rouge / max(n, 1),
        "accuracy_at_k": {str(k): hits[k] / max(n, 1) for k in KS},
        "gold_fully_in_candidates": covered_all / max(n, 1),
        "gold_partly_in_candidates": covered_any / max(n, 1),
        "rerank": _rerank_summary(rows) if reranker else None,
        "accuracy_at_1_by_facet": {
            facet: {"n": len(v), "acc": sum(v) / len(v)}
            for facet, v in sorted(by_facet.items())
        },
        "_rows": rows,
    }


def make_llm_reranker(llm, cache_dir: Path, concurrency: int = 4):
    """2.8's re-ranker as the harness's per-paper hook (see ``evaluate``).

    A failed call keeps the hybrid order for that citance and is flagged, never
    cached, and counted in the summary: a run with failures is incomplete.
    """
    import asyncio

    from app.core.llm_localizer import rerank
    from app.llm.client import LLMError

    loop = asyncio.new_event_loop()

    def run(citances, reference, shortlists):
        async def one(citance, shortlist, gate):
            async with gate:
                try:
                    r = await rerank(
                        citance.query, shortlist, llm, reference.source.title, cache_dir
                    )
                except LLMError as exc:
                    print(f"  ! {citance.key}: {exc}"[:200])
                    return shortlist[: max(KS)], {"llm_error": True}
                return r.results[: max(KS)], {
                    "any_fits": r.any_fits,
                    "confidence": r.confidence,
                    "dropped": r.dropped,
                    "cached": r.cached,
                }

        async def all_of():
            gate = asyncio.Semaphore(concurrency)
            return await asyncio.gather(
                *(one(c, s, gate) for c, s in zip(citances, shortlists))
            )

        # One loop for the whole run: the SDK's async client keeps connections
        # bound to the loop that opened them, so asyncio.run per paper fails
        # from the second paper on ("Event loop is closed").
        pairs = loop.run_until_complete(all_of())
        return [p[0] for p in pairs], [p[1] for p in pairs]

    return run


def _rerank_summary(rows: list[dict]) -> dict:
    def acc(group):
        return {
            "n": len(group),
            "acc_at_1": (
                sum(r["hit_at_1"] for r in group) / len(group) if group else None
            ),
        }

    ok = [r for r in rows if not r.get("llm_error")]
    return {
        "llm_errors": len(rows) - len(ok),
        "dropped_numbers": sum(r.get("dropped", 0) for r in ok),
        "from_cache": sum(bool(r.get("cached")) for r in ok),
        "by_confidence": {
            c: acc([r for r in ok if r.get("confidence") == c])
            for c in ("high", "medium", "low")
        },
        "by_any_fits": {
            str(v).lower(): acc([r for r in ok if r.get("any_fits") is v])
            for v in (True, False)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["all", "dev", "test"], default="all")
    parser.add_argument(
        "--ranker",
        choices=["embedding", "bm25", "hybrid", "random"],
        default="embedding",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-window", type=int, default=3, choices=[1, 2, 3])
    parser.add_argument(
        "--alpha", type=float, default=0.5, help="hybrid: embedding weight"
    )
    parser.add_argument(
        "--rerank",
        choices=["llm"],
        help="2.8: re-rank the hybrid's shortlist with the LLM",
    )
    parser.add_argument("--pool", type=int, default=POOL, help="re-rank shortlist size")
    parser.add_argument(
        "--concurrency", type=int, default=4, help="LLM calls in flight"
    )
    parser.add_argument(
        "--max-papers", type=int, help="Smoke test on the first N papers"
    )
    parser.add_argument("--save", action="store_true", help="Write results/*.json")
    args = parser.parse_args()
    if args.rerank and args.ranker != "hybrid":
        parser.error("--rerank re-orders the hybrid's shortlist: use --ranker hybrid")
    if args.save and args.max_papers:
        parser.error("--max-papers is a smoke test; its numbers are not results")
    reranker, llm_model = None, None
    if args.rerank:
        from app.llm.client import GeminiClient

        llm = GeminiClient()
        llm_model = llm.model
        reranker = make_llm_reranker(
            llm, HERE.parents[1] / "data" / "raw" / "llm-rerank-cache", args.concurrency
        )

    if not CORPUS.is_dir():
        print(f"Corpus not found at {CORPUS}; see clscisumm.py for how to get it.")
        return 1
    started = time.monotonic()
    result = evaluate(
        args.split,
        args.ranker,
        args.model,
        max_window=args.max_window,
        alpha=args.alpha,
        reranker=reranker,
        max_papers=args.max_papers,
        pool=args.pool,
    )
    result["llm"] = llm_model
    if llm_model:
        from app.config import get_settings

        result["llm_pool"] = args.pool
        result["llm_thinking_budget"] = get_settings().llm_thinking_budget
        llm_model += (f"-pool{args.pool}" if args.pool != POOL else "") + (
            f"-think{result['llm_thinking_budget']}"
            if result["llm_thinking_budget"]
            else ""
        )
    rows = result.pop("_rows")
    elapsed = time.monotonic() - started

    so, sp = result["sentence_overlap"], result["sentence_overlap_pooled"]
    name = {
        "embedding": result["model"],
        "hybrid": f"hybrid BM25 + {result['model']} (alpha {args.alpha})"
        + (f", re-ranked by {llm_model}" if llm_model else ""),
        "bm25": "BM25",
        "random": "random ranking",
    }[args.ranker] + (f", windows ≤ {args.max_window}" if args.max_window != 3 else "")
    print(f"CL-SciSumm Task 1A — {name} — split {args.split}")
    print(f"  {result['papers']} papers, {result['citances']} citances, {elapsed:.0f}s")
    print(
        f"  sentence overlap (official-style, avg over papers): "
        f"P {so['precision']:.3f}  R {so['recall']:.3f}  F1 {so['f1']:.3f}"
    )
    print(
        f"  sentence overlap (pooled over citances):            "
        f"P {sp['precision']:.3f}  R {sp['recall']:.3f}  F1 {sp['f1']:.3f}"
    )
    print(f"  ROUGE-L F1 (own implementation): {result['rouge_l_f1']:.3f}")
    print(
        "  accuracy@k: "
        + "  ".join(f"@{k} {v:.1%}" for k, v in result["accuracy_at_k"].items())
    )
    print(
        f"  gold reachable at all: fully {result['gold_fully_in_candidates']:.1%}, "
        f"partly {result['gold_partly_in_candidates']:.1%}"
    )
    print(
        "  accuracy@1 by facet: "
        + ", ".join(
            f"{f} {v['acc']:.0%} (n={v['n']})"
            for f, v in result["accuracy_at_1_by_facet"].items()
        )
    )
    if result["rerank"]:
        rr = result["rerank"]
        print(
            f"  re-rank: {rr['llm_errors']} failed calls, {rr['dropped_numbers']} "
            f"invalid numbers dropped, {rr['from_cache']} replies from cache"
        )
        for name in ("by_confidence", "by_any_fits"):
            print(
                f"  acc@1 {name.replace('_', ' ')}: "
                + ", ".join(
                    f"{k} {v['acc_at_1']:.0%} (n={v['n']})"
                    for k, v in rr[name].items()
                    if v["n"]
                )
            )
        if rr["llm_errors"]:
            print("  INCOMPLETE: some citances kept the hybrid order; re-run to fill")

    if args.save:
        RESULTS.mkdir(exist_ok=True)
        model_tag = args.model.split("/")[-1].replace("+", "-")
        tag = (
            {
                "embedding": f"embedding-{model_tag}",
                "hybrid": f"hybrid-{model_tag}-a{args.alpha}"
                + (f"-rerank-{llm_model}" if llm_model else ""),
                "bm25": "bm25",
                "random": "random-seed0",
            }[args.ranker]
            + (f"-w{args.max_window}" if args.max_window != 3 else "")
            + f"-{args.split}"
        )
        (RESULTS / f"{tag}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f"  saved results/{tag}.json")
        predictions = HERE.parents[1] / "data" / "raw" / "clscisumm-predictions"
        predictions.mkdir(parents=True, exist_ok=True)
        with (predictions / f"{tag}.jsonl").open("w") as out:
            out.writelines(json.dumps(row) + "\n" for row in rows)
        print(f"  per-citance predictions: data/raw/clscisumm-predictions/{tag}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
