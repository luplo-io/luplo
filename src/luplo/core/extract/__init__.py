"""Decision extraction from transcripts.

v0.5: stub only — returns empty results.  The interface is stable;
LLM integration (Claude API) will be swapped in post-v0.5.
"""

from luplo.core.extract.pipeline import extract_decisions, extract_glossary_candidates

__all__ = ["extract_decisions", "extract_glossary_candidates"]
