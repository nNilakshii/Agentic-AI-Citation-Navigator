"""Scholarly-metadata APIs. See ``client.py``."""

from app.scholar.client import ScholarError, SemanticScholar, get_scholar

__all__ = ["ScholarError", "SemanticScholar", "get_scholar"]
