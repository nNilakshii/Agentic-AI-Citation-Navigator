"""Parsing and document-model code. Deliberately free of FastAPI imports so the
evaluation harnesses in ``eval/`` can call it as a library."""

from app.core.pdf_parser import PARSER_VERSION, paper_id_for, parse_pdf

__all__ = ["PARSER_VERSION", "paper_id_for", "parse_pdf"]
