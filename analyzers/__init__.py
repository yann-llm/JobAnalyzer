"""LLM sub-agent analyzers for job-posting analysis."""

from inspect import signature
from typing import Any, Callable

from .basic_info_agent import analyze_basic_info
from .company_agent import analyze_company
from .company_finance_agent import analyze_company_finance
from .compensation_agent import analyze_compensation
from .final_evaluation_agent import analyze_final_evaluation
from .industry_outlook_agent import analyze_industry_outlook
from .legal_risk_agent import analyze_legal_risk
from .requirement_agent import analyze_requirements
from .responsibility_agent import analyze_responsibilities
from .work_intensity_agent import analyze_work_intensity

# Order matters only for display — execution is parallel.
ANALYZER_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "basic_info": analyze_basic_info,
    "responsibilities": analyze_responsibilities,
    "requirements": analyze_requirements,
    "compensation": analyze_compensation,
    "company": analyze_company,
    "work_intensity": analyze_work_intensity,
    "legal_risk": analyze_legal_risk,
    "industry_outlook": analyze_industry_outlook,
    "company_finance": analyze_company_finance,
}


def run_analyzer(
    analyzer: Callable[..., dict[str, Any]],
    cleaned: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an analyzer, passing ``candidate_profile`` only if it accepts it.

    Some agents (requirements / compensation / work_intensity) personalize
    their output when given a candidate profile; the rest take only the
    cleaned page. This dispatcher avoids unexpected-kwarg errors by
    introspecting each function's signature.
    """
    params = signature(analyzer).parameters
    if "candidate_profile" in params and candidate_profile is not None:
        return analyzer(cleaned, candidate_profile=candidate_profile)
    return analyzer(cleaned)


__all__ = [
    "ANALYZER_REGISTRY",
    "analyze_basic_info",
    "analyze_company",
    "analyze_company_finance",
    "analyze_compensation",
    "analyze_final_evaluation",
    "analyze_industry_outlook",
    "analyze_legal_risk",
    "analyze_requirements",
    "analyze_responsibilities",
    "analyze_work_intensity",
    "run_analyzer",
]
