"""External data sources used to ground LLM analysis with real facts.

The job-analysis pipeline can call out to QCC (企查查) over MCP streamable
HTTP to fetch real工商 / risk data for the hiring company. When external
data is present, ``company_risk`` uses those facts as the primary source for
company health and risk scoring.

Usage from ``main.py``::

    cleaned = clean_job_page(page)
    cleaned = enrich(cleaned)   # mutates cleaned["external"]["qcc"] if a company can be resolved

If ``QCC_AUTH_BEARER`` is not set or the call fails, ``enrich`` is a no-op
— the downstream pipeline falls back to model-only analysis.
"""

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from .enrich import clean_qcc_payload, enrich, has_qcc_config

__all__ = ["clean_qcc_payload", "enrich", "has_qcc_config"]
