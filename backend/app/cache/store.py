"""Content-addressed filesystem cache for PDFs and their parses.

Plain JSON files under ``data/cache/`` — no database until something forces one
(``docs/architecture.md``). Parses are keyed by ``sha256(pdf_bytes)`` *and*
``parser_version``: re-parsing after a parser change writes a new file rather
than overwriting one whose offsets other artifacts already point into.
"""

import json
from pathlib import Path

from app.models.paper import ParsedPaper

#: Repo root -> data/cache. Gitignored; see .gitignore.
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"


class PaperStore:
    """Stores uploaded PDFs and their parsed representations on disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_CACHE_DIR
        self.pdf_dir = self.root / "pdfs"
        self.parsed_dir = self.root / "parsed"

    # --- paths ---------------------------------------------------------

    def pdf_path(self, paper_id: str) -> Path:
        return self.pdf_dir / f"{paper_id}.pdf"

    def parsed_path(self, paper_id: str, parser_version: str) -> Path:
        return self.parsed_dir / f"{paper_id}.v{parser_version}.json"

    # --- reads ---------------------------------------------------------

    def load_pdf(self, paper_id: str) -> bytes | None:
        path = self.pdf_path(paper_id)
        return path.read_bytes() if path.exists() else None

    def load_parsed(self, paper_id: str, parser_version: str) -> ParsedPaper | None:
        """Return the cached parse, or ``None`` if absent or unreadable.

        A corrupt cache file is treated as a miss: the PDF is the source of
        truth and re-parsing is cheap, so a half-written file should never be a
        hard failure.
        """
        path = self.parsed_path(paper_id, parser_version)
        if not path.exists():
            return None
        try:
            return ParsedPaper.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def list_parsed(self, parser_version: str) -> list[ParsedPaper]:
        """Every paper parsed at this parser version, newest write first."""
        if not self.parsed_dir.exists():
            return []
        paths = sorted(
            self.parsed_dir.glob(f"*.v{parser_version}.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        papers = []
        for path in paths:
            paper = self.load_parsed(path.name.split(".v")[0], parser_version)
            if paper is not None:
                papers.append(paper)
        return papers

    # --- writes --------------------------------------------------------

    def save_pdf(self, paper_id: str, pdf_bytes: bytes) -> Path:
        path = self.pdf_path(paper_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(path, pdf_bytes)
        return path

    def save_parsed(self, paper: ParsedPaper) -> Path:
        path = self.parsed_path(paper.paper_id, paper.parser_version)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(paper.model_dump(), ensure_ascii=False)
        self._write_atomic(path, payload.encode("utf-8"))
        return path

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        """Write via a temp file and rename, so readers never see a partial file."""
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)
