"""Check candidate passages on the samples and the fetched cited papers (2.4).

Per paper: how many sentences survive as candidates, how many passages that
makes, and what was left out by reason. Then two checks a human should read:

- **Bibliography leaks.** Independent of the rule that removes the reference
  list, every kept three-sentence passage is tested for looking like
  reference entries. The sentence splitter breaks an entry into fragments
  ("(1990).", a title, a venue), so single sentences carry too little signal;
  three together usually do. The check catches ~40% of bibliography windows
  and fires on ~0.2% of body text — too weak for single entries, plenty to
  notice a whole leaked list. Its recall on the text that *was* removed is
  printed on every run, so a detector that stops working is visible (the
  first version scored 1 in 2,400 and reported "0 leaks").
- **Papers that lost most of their text** (under ``MIN_KEPT`` of sentences),
  or had no reference heading at all, so nothing was removed.

Cited papers come from ``data/fetch-qa/`` (run ``qa_fetch.py`` first).

    python scripts/qa_passages.py
"""

from __future__ import annotations

import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.passages import passages_from_paper  # noqa: E402
from app.models.paper import ParsedPaper  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DIRS = [ROOT / "data" / "cache" / "parsed", ROOT / "data" / "fetch-qa" / "parsed"]
#: The user's own upload, never part of QA (see .gitignore).
PRIVATE = "531176d05f81f3955cc1f0d4893ec94ede2ebf27e77422eb3b243678af7dc915"
MIN_KEPT = 0.30
#: Per paper, among kept three-sentence passages. Body text alone sits ~0.2%.
MAX_LEAK_RATE = 0.02

_STRONG = [
    re.compile(r"(?:\.|\()\s?(?:19|20)\d{2}[a-z]?[.)]"),
    re.compile(
        r"\b(?:Proceedings|Proc\.|arXiv preprint|CoRR|Journal|Conference|Workshop|"
        r"Transactions|Association for Computational|Press)\b"
    ),
    re.compile(r"\b(?:pp\.|pages)\s?\d+|\d+\s?[–-]\s?\d+[.,]"),
    re.compile(r"(?:[A-Z][a-z]+(?:[- ][A-Z][a-z]+)?,\s){2,}"),
    re.compile(r"https?://|doi\.org"),
]
_PROSE_WORDS = re.compile(r"\b(?:we|We|our|Our|is|are|was|were)\b")


def looks_like_references(text: str) -> bool:
    strong = sum(bool(r.search(text)) for r in _STRONG)
    return strong >= 2 and not _PROSE_WORDS.search(text)


def main() -> int:
    totals: Counter[str] = Counter()
    kept_shares: list[float] = []
    counts: list[int] = []
    leaks: list[str] = []
    flagged: list[str] = []
    removed_hits = removed_windows = 0

    files = [f for d in DIRS for f in sorted(d.glob("*.json")) if PRIVATE not in f.name]
    for path in files:
        paper = ParsedPaper.model_validate_json(path.read_text(encoding="utf-8"))
        if not paper.sentences:
            continue
        result = passages_from_paper(paper)
        name = (paper.source.title or paper.source.filename)[:40]
        kept = {i for p in result.passages for i in p.sentence_ids}
        share = len(kept) / len(paper.sentences)
        kept_shares.append(share)
        counts.append(len(result.passages))
        totals.update(result.excluded)
        if share < MIN_KEPT:
            flagged.append(f"{name}: kept {share:.0%} — {result.excluded}")
        if "reference list" not in result.excluded:
            flagged.append(f"{name}: no reference list found; nothing removed")
        triples = [p for p in result.passages if len(p.sentence_ids) == 3]
        hits = [p for p in triples if looks_like_references(p.text)]
        if triples and len(hits) / len(triples) > MAX_LEAK_RATE:
            leaks.append(
                f"{name}: {len(hits)}/{len(triples)} windows look like references"
            )
            leaks.extend(f"    {p.text[:100]!r}" for p in hits[:3])

        # Detector sanity: the same test on the reference list that was removed.
        kept_ids = {i for p in result.passages for i in p.sentence_ids}
        sents = paper.sentences
        for i in range(len(sents) - 2):
            window = sents[i : i + 3]
            if any(s.id in kept_ids for s in window):
                continue
            text = paper.full_text[window[0].start_char : window[-1].end_char]
            if _in_reference_list(paper, window[0].start_char):
                removed_windows += 1
                removed_hits += looks_like_references(text)

    n = len(kept_shares)
    print(
        f"{n} papers. Sentences kept as candidates: median {statistics.median(kept_shares):.0%}, "
        f"lowest {min(kept_shares):.0%}."
    )
    print(
        f"Passages per paper: median {statistics.median(counts):.0f}, max {max(counts)}."
    )
    print(
        "Left out, all papers: "
        + ", ".join(f"{k} {v}" for k, v in totals.most_common())
    )
    if flagged:
        print("\nFlagged papers:")
        print("\n".join(f"  {line}" for line in flagged))
    recall = removed_hits / max(removed_windows, 1)
    print(
        f"\nLeak detector recall on removed reference lists: {recall:.0%} "
        f"({removed_windows} windows) — if this is near 0, the check below is blind."
    )
    if leaks:
        print("Papers whose kept passages look like a reference list:")
        print("\n".join(f"  {line}" for line in leaks))
    else:
        print(f"No paper over {MAX_LEAK_RATE:.0%} reference-like windows.")
    return 0 if not leaks and recall >= 0.2 else 1


def _in_reference_list(paper: ParsedPaper, offset: int) -> bool:
    section = next(
        (s for s in paper.sections if s.start_char <= offset < s.end_char), None
    )
    return bool(
        section
        and re.match(
            r"^\s*(?:\d+\.?\s+)?(?:references|bibliography)\s*$", section.title, re.I
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
