"""External data sources used to ground LLM analysis with real facts.

The job-analysis pipeline can call out to QCC (企查查) over MCP streamable
HTTP to fetch real工商 / risk data for the hiring company. When external
data is present, ``company_risk`` uses those facts as the primary source for
company health and risk scoring.

Usage from ``main.py``::

    cleaned = clean_job_page(page)
    cleaned = enrich(cleaned)   # mutates cleaned["external"]["qcc"] if a company can be resolved

The pipeline only trusts unified social credit codes scraped from the job or
company pages. Once a valid USCC is available, the company entity is treated as
anchored and QCC is used to fetch company facts for LLM analysis.
"""

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from .enrich import clean_qcc_payload, enrich, has_qcc_config

__all__ = ["clean_qcc_payload", "enrich", "has_qcc_config"]
