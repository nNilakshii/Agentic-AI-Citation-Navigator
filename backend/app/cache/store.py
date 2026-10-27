"""Content-addressed filesystem cache for PDFs and their parses.

Plain JSON files under ``data/cache/`` — no database until something forces one
(``docs/architecture.md``). Parses are keyed by ``sha256(pdf_bytes)`` *and*
``parser_version``: re-parsing after a parser change writes a new file rather
than overwriting one whose offsets other artifacts already point into.
"""

import json
from pathlib import Path

from app.models.paper import ParsedPaper
from app.models.reading import ReadingGoal, ReadingPath
from app.models.resolution import ResolutionMap

#: Repo root -> data/cache. Gitignored; see .gitignore.
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"


class PaperStore:
    """Stores uploaded PDFs and their parsed representations on disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_CACHE_DIR
        self.pdf_dir = self.root / "pdfs"
        self.parsed_dir = self.root / "parsed"
        self.paths_dir = self.root / "reading_paths"
        self.resolutions_dir = self.root / "resolutions"

    # --- paths ---------------------------------------------------------

    def pdf_path(self, paper_id: str) -> Path:
        return self.pdf_dir / f"{paper_id}.pdf"

    def parsed_path(self, paper_id: str, parser_version: str) -> Path:
        return self.parsed_dir / f"{paper_id}.v{parser_version}.json"

    def reading_path_path(
        self, paper_id: str, parser_version: str, goal: ReadingGoal, ranker_version: str
    ) -> Path:
        # Keyed by parser *and* ranker version: a reparse moves the offsets a
        # path points into, and a prompt change means the old ranking is no
        # longer what this ranker would produce.
        return (
            self.paths_dir
            / f"{paper_id}.v{parser_version}.{goal.value}.r{ranker_version}.json"
        )

    def resolution_path(
        self,
        paper_id: str,
        parser_version: str,
        citation_version: str,
        resolver_version: str,
        title_search: bool,
    ) -> Path:
        # Every version that could change a resolution is in the key, so a
        # change to parsing, citation detection or matching never serves a
        # stale one.
        suffix = ".ts" if title_search else ""
        name = f"{paper_id}.v{parser_version}.c{citation_version}.r{resolver_version}{suffix}.json"
        return self.resolutions_dir / name

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

    def load_reading_path(
        self, paper_id: str, parser_version: str, goal: ReadingGoal, ranker_version: str
    ) -> ReadingPath | None:
        """Return the cached path, or ``None`` if absent or unreadable.

        Same reasoning as :meth:`load_parsed`: a corrupt file is a miss, not a
        failure — LLM calls cost quota but are reproducible.
        """
        path = self.reading_path_path(paper_id, parser_version, goal, ranker_version)
        if not path.exists():
            return None
        try:
            return ReadingPath.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def load_resolution(self, *key, title_search: bool = False) -> ResolutionMap | None:
        """A cached resolution, or ``None`` if absent or unreadable."""
        path = self.resolution_path(*key, title_search)
        if not path.exists():
            return None
        try:
            return ResolutionMap.model_validate_json(path.read_text(encoding="utf-8"))
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

    def save_reading_path(self, reading_path: ReadingPath) -> Path:
        path = self.reading_path_path(
            reading_path.paper_id,
            reading_path.parser_version,
            reading_path.goal,
            reading_path.ranker_version,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(reading_path.model_dump(mode="json"), ensure_ascii=False)
        self._write_atomic(path, payload.encode("utf-8"))
        return path

    def save_resolution(
        self, resolution: ResolutionMap, *, title_search: bool = False
    ) -> Path:
        path = self.resolution_path(
            resolution.paper_id,
            resolution.parser_version,
            resolution.citation_version,
            resolution.resolver_version,
            title_search,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(resolution.model_dump(mode="json"), ensure_ascii=False)
        self._write_atomic(path, payload.encode("utf-8"))
        return path

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        """Write via a temp file and rename, so readers never see a partial file."""
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)
