"""LLM sub-agent analyzers for job-posting analysis."""

from inspect import signature
from typing import Any, Callable

from .company_risk_agent import analyze_company_risk
from .final_evaluation_agent import analyze_final_evaluation
from .industry_outlook_agent import analyze_industry_outlook
from .job_value_agent import analyze_job_value

# Order matters only for display — execution is parallel.
ANALYZER_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "job_value": analyze_job_value,
    "company_risk": analyze_company_risk,
    "industry_outlook": analyze_industry_outlook,
}


def run_analyzer(
    analyzer: Callable[..., dict[str, Any]],
    cleaned: dict[str, Any],
    *,
    qcc_cleaned: dict[str, Any] | None = None,
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an analyzer, passing optional inputs only if it accepts them.

    Some agents personalize their output when given a candidate profile.
    Company-related agents can receive ``qcc_cleaned`` so QCC facts are the
    primary company source. This dispatcher avoids unexpected-kwarg errors by
    introspecting each function's signature.
    """
    params = signature(analyzer).parameters
    kwargs: dict[str, Any] = {}
    if "qcc_cleaned" in params and qcc_cleaned is not None:
        kwargs["qcc_cleaned"] = qcc_cleaned
    if "candidate_profile" in params and candidate_profile is not None:
        kwargs["candidate_profile"] = candidate_profile
    return analyzer(cleaned, **kwargs)


__all__ = [
    "ANALYZER_REGISTRY",
    "analyze_company_risk",
    "analyze_final_evaluation",
    "analyze_industry_outlook",
    "analyze_job_value",
    "run_analyzer",
]
