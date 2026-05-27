"""External data sources used to ground LLM analysis with real facts.

The job-analysis pipeline can call out to QCC (企查查) over MCP streamable
HTTP to fetch real工商 / risk data for the hiring company. When external
data is present, three sub-agents (company / company_finance / legal_risk)
switch from model-recall guesses to data-grounded facts and label their
provenance accordingly.

Usage from ``main.py``::

    cleaned = clean_job_page(page)
    cleaned = enrich(cleaned)   # mutates cleaned["external"]["qcc"] if a company can be resolved

If no ``qcc_config.json`` exists or the call fails, ``enrich`` is a no-op
— the downstream pipeline falls back to model-only analysis.
"""

from .enrich import enrich, has_qcc_config

__all__ = ["enrich", "has_qcc_config"]
