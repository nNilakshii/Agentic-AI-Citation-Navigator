"""Tests for the pure helpers in `scripts/fetch_sample_papers.py` (task 0.7).

Network calls aren't exercised here — only feed parsing, selection and manifest merging.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# `scripts/` isn't a package, so load the module by path. It must be registered in
# sys.modules before exec_module, or @dataclass can't resolve its own annotations.
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_sample_papers.py"
spec = importlib.util.spec_from_file_location("fetch_sample_papers", SCRIPT)
fsp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fsp
spec.loader.exec_module(fsp)


FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All
      You Need</title>
    <published>2017-06-12T17:57:34Z</published>
    <updated>2023-08-02T00:41:18Z</updated>
    <link href="https://arxiv.org/abs/1706.03762v7" rel="alternate"/>
    <link href="https://arxiv.org/pdf/1706.03762v7" title="pdf" rel="related"/>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
  </entry>
</feed>
"""


def test_parse_entries_keys_on_bare_id_and_normalizes_fields():
    entries = fsp.parse_entries(FEED)

    assert set(entries) == {"1706.03762"}  # versioned id stripped
    entry = entries["1706.03762"]
    assert entry["title"] == "Attention Is All You Need"  # whitespace collapsed
    assert entry["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    # Downloads go through the mirror arXiv asks programmatic clients to use.
    assert entry["pdf_url"] == "https://export.arxiv.org/pdf/1706.03762v7"


def test_parse_entries_handles_empty_feed():
    assert fsp.parse_entries('<feed xmlns="http://www.w3.org/2005/Atom"/>') == {}


def test_curated_ids_are_unique_and_well_formed():
    ids = [p[0] for p in fsp.PAPERS]
    slugs = [p[1] for p in fsp.PAPERS]

    assert len(ids) == len(set(ids)), "duplicate arXiv ID in the curated list"
    assert len(slugs) == len(set(slugs)), "duplicate slug would overwrite a PDF"
    assert 5 <= len(ids) <= 10, "task 0.7 asks for 5-10 papers"


def test_select_papers_honours_limit_and_ids():
    assert len(fsp.select_papers(None, 3)) == 3
    assert [p[0] for p in fsp.select_papers(["1706.03762"], None)] == ["1706.03762"]

    # An ID outside the curated list is still fetchable, with a derived slug.
    ad_hoc = fsp.select_papers(["2301.00001"], None)
    assert ad_hoc == [("2301.00001", "arxiv-2301-00001", "ad hoc")]


def test_partial_run_preserves_earlier_manifest_entries(tmp_path):
    (tmp_path / "bert.pdf").write_bytes(b"%PDF-1.4 stub")
    (tmp_path / "rag.pdf").write_bytes(b"%PDF-1.4 stub")

    first = [fsp.PaperMeta("1810.04805", "bert", "x", filename="bert.pdf")]
    second = [fsp.PaperMeta("2005.11401", "rag", "y", filename="rag.pdf")]

    fsp.write_manifest(tmp_path, first)
    manifest = fsp.write_manifest(tmp_path, second)

    data = json.loads(manifest.read_text())
    assert data["count"] == 2
    assert {p["slug"] for p in data["papers"]} == {"bert", "rag"}


def test_manifest_drops_entries_whose_pdf_is_gone(tmp_path):
    (tmp_path / "bert.pdf").write_bytes(b"%PDF-1.4 stub")
    fsp.write_manifest(
        tmp_path, [fsp.PaperMeta("1810.04805", "bert", "x", filename="bert.pdf")]
    )
    (tmp_path / "bert.pdf").unlink()

    data = json.loads(fsp.write_manifest(tmp_path, []).read_text())
    assert data["papers"] == []


@pytest.mark.parametrize("content", ["not json at all", '{"papers": [}'])
def test_unreadable_manifest_is_rebuilt(tmp_path, content):
    (tmp_path / "manifest.json").write_text(content)
    (tmp_path / "rag.pdf").write_bytes(b"%PDF-1.4 stub")

    manifest = fsp.write_manifest(
        tmp_path, [fsp.PaperMeta("2005.11401", "rag", "y", filename="rag.pdf")]
    )
    assert json.loads(manifest.read_text())["count"] == 1
