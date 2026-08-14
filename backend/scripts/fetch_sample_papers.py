"""Download a curated set of open-access arXiv PDFs into `data/samples/`.

Task 0.7. These papers are the dev/test corpus for Phase 1 (parsing, goal-adaptive
reading) and Phase 2 (citation bridge), so the list is deliberately biased toward
papers with long, dense reference lists and many inline citations.

Usage (from the repo root, with the backend venv active):

    python backend/scripts/fetch_sample_papers.py            # fetch all, skip existing
    python backend/scripts/fetch_sample_papers.py --limit 5  # just the first 5
    python backend/scripts/fetch_sample_papers.py --force    # re-download everything
    python backend/scripts/fetch_sample_papers.py --ids 1706.03762 2005.11401

Writes the PDFs plus a `manifest.json` recording the resolved arXiv metadata. Both are
gitignored (see root `.gitignore`) — this script is the committed source of truth, so
re-running it reproduces the corpus.

arXiv asks API clients for a descriptive User-Agent and roughly one request every three
seconds; both are respected below. Please don't lower `REQUEST_DELAY_SECONDS`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import requests

# --- Curated corpus -----------------------------------------------------------------
# Each entry is (arXiv ID, output slug, why it's here). Every ID was verified against
# the arXiv API on 2026-08-14. Slugs become the PDF filenames, so keep them stable —
# fixtures and eval configs may refer to them.
PAPERS: list[tuple[str, str, str]] = [
    (
        "2303.14334",
        "semantic-reader",
        "Prior work: AI-powered interactive reading interfaces",
    ),
    (
        "1907.09854",
        "cl-scisumm-2019",
        "Phase 2 benchmark: cited-span localization shared task",
    ),
    (
        "1904.01608",
        "scicite-scaffolds",
        "Phase 3 benchmark: citation-intent classification",
    ),
    ("2004.07180", "specter", "Citation-informed document embeddings"),
    ("1903.10676", "scibert", "Pretrained LM for scientific text"),
    ("1908.10084", "sentence-bert", "Sentence embeddings; retrieval baseline"),
    ("2005.11401", "rag", "Retrieval-augmented generation; grounding for Phase 3"),
    (
        "2004.05150",
        "longformer",
        "Long-document transformer; dense related-work section",
    ),
    ("1810.04805", "bert", "Heavily cited, well-structured, familiar ground truth"),
    (
        "1706.03762",
        "attention-is-all-you-need",
        "Short paper, many citations; quick smoke test",
    ),
]

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
USER_AGENT = (
    "AURA-Citation-Navigator/0.1 (USC research project; "
    "https://github.com/; mailto:nilakshii.nagrale@gmail.com)"
)
REQUEST_DELAY_SECONDS = 3.0
REQUEST_TIMEOUT_SECONDS = 60
MIN_PDF_BYTES = 10_000

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "samples"


@dataclass
class PaperMeta:
    """Metadata for one arXiv paper, as resolved from the Atom API."""

    arxiv_id: str
    slug: str
    reason: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    pdf_url: str = ""
    abs_url: str = ""
    filename: str = ""
    size_bytes: int = 0


def parse_entries(feed_xml: str) -> dict[str, dict]:
    """Parse an arXiv Atom feed into {bare_arxiv_id: metadata dict}.

    The API echoes versioned IDs (``1706.03762v7``); we key on the bare ID so callers
    can look entries up by the ID they asked for.
    """
    root = ET.fromstring(feed_xml)
    entries: dict[str, dict] = {}

    for entry in root.findall("atom:entry", ATOM_NS):
        id_url = (entry.findtext("atom:id", default="", namespaces=ATOM_NS)).strip()
        versioned_id = id_url.rsplit("/abs/", 1)[-1]
        bare_id = versioned_id.split("v")[0]
        if not bare_id:
            continue

        pdf_url = ""
        for link in entry.findall("atom:link", ATOM_NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{versioned_id}"
        # export.arxiv.org is the mirror arXiv asks programmatic clients to use.
        pdf_url = pdf_url.replace("//arxiv.org/", "//export.arxiv.org/")

        entries[bare_id] = {
            "title": " ".join(
                entry.findtext("atom:title", default="", namespaces=ATOM_NS).split()
            ),
            "authors": [
                a.findtext("atom:name", default="", namespaces=ATOM_NS).strip()
                for a in entry.findall("atom:author", ATOM_NS)
            ],
            "published": entry.findtext(
                "atom:published", default="", namespaces=ATOM_NS
            ),
            "updated": entry.findtext("atom:updated", default="", namespaces=ATOM_NS),
            "categories": [
                c.get("term", "") for c in entry.findall("atom:category", ATOM_NS)
            ],
            "pdf_url": pdf_url,
            "abs_url": id_url,
        }

    return entries


def fetch_metadata(arxiv_ids: list[str], session: requests.Session) -> dict[str, dict]:
    """Resolve metadata for all IDs in a single arXiv API call."""
    response = session.get(
        ARXIV_API_URL,
        params={"id_list": ",".join(arxiv_ids), "max_results": len(arxiv_ids)},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return parse_entries(response.text)


def download_pdf(url: str, dest: Path, session: requests.Session) -> int:
    """Stream a PDF to `dest`, returning its size in bytes.

    Downloads to a temporary `.part` file and only renames on success, so an
    interrupted run never leaves a half-written PDF that a later run would skip.
    Raises ValueError if the response isn't a plausible PDF.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with session.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    handle.write(chunk)

        size = tmp.stat().st_size
        if size < MIN_PDF_BYTES:
            raise ValueError(
                f"suspiciously small ({size} bytes) — probably not the PDF"
            )
        with tmp.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError("response is not a PDF (missing %PDF- header)")

        tmp.replace(dest)
        return size
    finally:
        tmp.unlink(missing_ok=True)


def select_papers(
    ids: list[str] | None, limit: int | None
) -> list[tuple[str, str, str]]:
    """Pick which curated entries to fetch, honouring --ids and --limit."""
    papers = PAPERS
    if ids:
        wanted = {i.strip() for i in ids}
        papers = [p for p in papers if p[0] in wanted]
        unknown = wanted - {p[0] for p in PAPERS}
        for arxiv_id in sorted(unknown):
            # Not in the curated list, but still fetchable — slug from the ID.
            papers = papers + [
                (arxiv_id, f"arxiv-{arxiv_id.replace('.', '-')}", "ad hoc")
            ]
    if limit is not None:
        papers = papers[:limit]
    return papers


def merge_manifest_papers(
    existing: list[dict], resolved: list[PaperMeta]
) -> list[dict]:
    """Merge this run's papers into the previously recorded ones, keyed by slug.

    A partial run (`--limit`, `--ids`) must not erase the record of papers fetched
    earlier, so entries this run didn't touch are carried through unchanged.
    """
    by_slug = {entry.get("slug"): entry for entry in existing if entry.get("slug")}
    for paper in resolved:
        by_slug[paper.slug] = vars(paper)
    return [by_slug[slug] for slug in sorted(by_slug)]


def write_manifest(out_dir: Path, resolved: list[PaperMeta]) -> Path:
    """Write `manifest.json`, preserving entries from earlier runs."""
    manifest = out_dir / "manifest.json"

    existing: list[dict] = []
    if manifest.exists():
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8")).get(
                "papers", []
            )
        except (json.JSONDecodeError, OSError):
            existing = []  # unreadable manifest: rebuild from this run alone

    # Drop entries whose PDF has since been deleted, so the manifest stays truthful.
    existing = [e for e in existing if (out_dir / str(e.get("filename", ""))).exists()]
    papers = merge_manifest_papers(existing, resolved)

    manifest.write_text(
        json.dumps(
            {
                "source": "arXiv (open access)",
                "fetched_by": "backend/scripts/fetch_sample_papers.py",
                "count": len(papers),
                "papers": papers,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="fetch only the first N"
    )
    parser.add_argument("--ids", nargs="+", default=None, help="specific arXiv IDs")
    parser.add_argument(
        "--force", action="store_true", help="re-download existing PDFs"
    )
    args = parser.parse_args()

    papers = select_papers(args.ids, args.limit)
    if not papers:
        print("Nothing to fetch.", file=sys.stderr)
        return 1

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    print(f"Resolving {len(papers)} papers via the arXiv API...")
    try:
        metadata = fetch_metadata([p[0] for p in papers], session)
    except requests.RequestException as exc:
        print(f"arXiv API request failed: {exc}", file=sys.stderr)
        return 1

    resolved: list[PaperMeta] = []
    failures: list[str] = []

    for index, (arxiv_id, slug, reason) in enumerate(papers):
        entry = metadata.get(arxiv_id)
        if entry is None:
            print(f"  [skip] {arxiv_id} — not returned by the arXiv API")
            failures.append(arxiv_id)
            continue

        paper = PaperMeta(arxiv_id=arxiv_id, slug=slug, reason=reason, **entry)
        dest = out_dir / f"{slug}.pdf"
        paper.filename = dest.name

        if dest.exists() and not args.force:
            paper.size_bytes = dest.stat().st_size
            resolved.append(paper)
            print(f"  [have] {slug}.pdf — {paper.title[:60]}")
            continue

        if index > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            paper.size_bytes = download_pdf(paper.pdf_url, dest, session)
        except (requests.RequestException, ValueError, OSError) as exc:
            print(f"  [fail] {slug} ({arxiv_id}) — {exc}", file=sys.stderr)
            failures.append(arxiv_id)
            continue

        resolved.append(paper)
        print(
            f"  [ok]   {slug}.pdf — {paper.size_bytes / 1_048_576:.1f} MB — {paper.title[:60]}"
        )

    manifest = write_manifest(out_dir, resolved)
    total = json.loads(manifest.read_text(encoding="utf-8"))["count"]

    print(f"\n{total} PDF(s) in {out_dir}; manifest written to {manifest.name}")
    if failures:
        print(f"Failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
