"""Put every sample PDF into the PDF store, under its paper id.

Run at image build time, after ``fetch_sample_papers.py``. The committed parses
let the API answer for a sample without re-parsing, but the reader also fetches
the PDF bytes, and those live in the store rather than the repo. Seeding them
into the image means every instance can serve every sample's PDF from the
moment it starts — no reliance on which instance happened to handle the
request that opened the paper.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import PaperStore  # noqa: E402
from app.core.pdf_parser import paper_id_for  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def main() -> int:
    store = PaperStore()
    pdfs = sorted(SAMPLES.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {SAMPLES}; run fetch_sample_papers.py first.")
        return 1
    for pdf in pdfs:
        data = pdf.read_bytes()
        store.save_pdf(paper_id_for(data), data)
    print(f"Seeded {len(pdfs)} sample PDFs into {store.pdf_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
