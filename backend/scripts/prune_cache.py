"""Keep non-sample papers out of the committed cache.

``data/cache/parsed/`` and ``data/cache/reading_paths/`` are committed so the
deployed image can serve every sample paper without an LLM call. But the same
directories fill up with whatever a developer opened locally — their own PDFs,
stored with full text — and those must never be published.

This reports (and optionally removes) any cached artifact that does not belong
to a file in ``data/samples/``.

    python scripts/prune_cache.py --check   # exit 1 if anything foreign, CI-friendly
    python scripts/prune_cache.py           # list what would be removed
    python scripts/prune_cache.py --delete  # remove it
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
PARSED = ROOT / "data" / "cache" / "parsed"
PATHS = ROOT / "data" / "cache" / "reading_paths"


def sample_ids() -> dict[str, str]:
    return {
        hashlib.sha256(p.read_bytes()).hexdigest(): p.name
        for p in sorted(SAMPLES.glob("*.pdf"))
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="Remove what is found")
    parser.add_argument("--check", action="store_true", help="Exit 1 if anything found")
    args = parser.parse_args()

    known = sample_ids()
    if not known:
        print(f"No sample PDFs in {SAMPLES} — run scripts/fetch_sample_papers.py.")
        return 1

    foreign: list[Path] = []
    for directory in (PARSED, PATHS):
        for file in sorted(directory.glob("*.json")):
            paper_id = file.name.split(".v")[0]
            if paper_id not in known:
                foreign.append(file)

    if not foreign:
        print(f"Cache is clean: {len(known)} sample papers, nothing foreign.")
        return 0

    print(f"{len(foreign)} cached artifact(s) not from data/samples/:")
    for file in foreign:
        label = ""
        if file.parent == PARSED:
            try:
                label = json.loads(file.read_text())["source"]["filename"]
            except (ValueError, OSError, KeyError):
                label = "unreadable"
        print(f"  {file.relative_to(ROOT)}  {label}")

    if args.delete:
        for file in foreign:
            file.unlink()
        print(f"\nRemoved {len(foreign)} file(s).")
        return 0

    print(
        "\nThese must not be committed — they hold the full text of PDFs opened\n"
        "locally. Re-run with --delete, or confirm .gitignore excludes them."
    )
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
