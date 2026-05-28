"""Adapters from persisted analyzer artifacts to the frontend API contract."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"

DIMENSION_MAP: tuple[tuple[str, str, str], ...] = (
    ("responsibility", "职责质量", "职责质量"),
    ("requirements", "要求合理性", "要求合理性"),
    ("compensation", "薪酬福利", "薪酬福利"),
    ("workload", "工作强度", "工作强度"),
    ("companyHealth", "公司评分", "统一评分"),
    ("industryOutlook", "行业评分", "行业评分"),
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def result_dirs() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    dirs = [p for p in DATA_DIR.iterdir() if p.is_dir() and (p / "analysis.json").exists()]
    return sorted(dirs, key=lambda p: (p / "analysis.json").stat().st_mtime, reverse=True)


def load_result_artifacts(result_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_dir = DATA_DIR / result_id
    if not base_dir.is_dir():
        raise FileNotFoundError(result_id)
    analysis_path = base_dir / "analysis.json"
    if not analysis_path.exists():
        raise FileNotFoundError(result_id)
    job = read_json(base_dir / "job_cleaned.json") if (base_dir / "job_cleaned.json").exists() else {}
    company = read_json(base_dir / "company.json") if (base_dir / "company.json").exists() else {}
    return base_dir, read_json(analysis_path), job, company


def build_job_analysis(result_id: str, *, include_details: bool = True) -> dict[str, Any]:
    _, analysis, job, company_ref = load_result_artifacts(result_id)
    modules = analysis.get("modules") or {}
    job_value = _module_analysis(modules.get("job_value"))
    company_risk = _module_analysis(modules.get("company_risk"))
    industry_outlook = _module_analysis(modules.get("industry_outlook"))
    final = _module_analysis(analysis.get("final"))

    job_profile = _dict(job_value.get("岗位画像"))
    final_profile = _dict(final.get("岗位画像"))
    recommendation = _dict(final.get("申请建议"))
    fit = _dict(_dict(final.get("匹配建议")).get("vs 候选人画像"))

    title = _text(job.get("职位名称") or job_profile.get("岗位名称") or "未命名职位")
    company_id = _company_id(company_ref, job, company_risk)
    company_name = _company_name(company_ref, job, company_risk)
    total = _score(final.get("综合评分"))
    action = _text(recommendation.get("建议动作") or _action_from_score(total))
    grade_text = f"{_grade_letter(total)} · {_tag_text(action, total)}"

    scores = _dimension_scores(job_value, company_risk, industry_outlook)
    details = _dimension_details(job_value, company_risk, industry_outlook)
    payload: dict[str, Any] = {
        "id": result_id,
        "generatedAt": _text(analysis.get("generated_at")),
        "title": title,
        "code": _job_code(analysis.get("url"), result_id),
        "level": "",
        "matchTag": _match_tag(fit, total),
        "company": company_id,
        "meta": _job_meta(job, job_profile),
        "summaryMeta": _summary_meta(job, company_risk, industry_outlook),
        "scores": scores,
        "total": total,
        "grade": grade_text,
        "miniLabel": _mini_label(company_name, title, job_profile, final_profile),
        "miniTag": {"text": _tag_text(action, total), "cls": _badge_cls(total)},
        "summary": _summary(final, job_value, company_risk, industry_outlook),
        "pros": _string_list(final.get("优势亮点"))[:5],
        "cons": _string_list(final.get("潜在风险"))[:5],
        "details": details,
    }
    if not include_details:
        payload.pop("details", None)
    return payload


def build_company(company_id: str) -> dict[str, Any] | None:
    for result_dir in result_dirs():
        result_id = result_dir.name
        try:
            _, analysis, job, company_ref = load_result_artifacts(result_id)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        modules = analysis.get("modules") or {}
        company_risk = _module_analysis(modules.get("company_risk"))
        industry_outlook = _module_analysis(modules.get("industry_outlook"))
        if company_id not in {
            _company_id(company_ref, job, company_risk),
            _text(company_ref.get("uscc")),
            _text(company_ref.get("company_name")),
        }:
            continue
        return _company_payload(company_id, job, company_ref, company_risk, industry_outlook)
    return None


def _company_payload(
    company_id: str,
    job: dict[str, Any],
    company_ref: dict[str, Any],
    company_risk: dict[str, Any],
    industry_outlook: dict[str, Any],
) -> dict[str, Any]:
    profile = _dict(company_risk.get("公司画像"))
    unified = _dict(company_risk.get("统一评分"))
    industry_score = _dict(industry_outlook.get("行业评分"))
    industry_name = _industry_name(profile, industry_outlook)
    founded = _text(profile.get("成立时间") or _dict(job.get("工商信息")).get("成立日期"))
    info = [
        ["统一信用代码", _text(profile.get("统一社会信用代码") or company_ref.get("uscc"))],
        ["法定代表人", _text(profile.get("实际控制人") or _dict(job.get("工商信息")).get("法定代表人"))],
        ["注册资本", _text(profile.get("注册资本") or _dict(job.get("工商信息")).get("注册资金"))],
        ["参保人数", _text(profile.get("参保人数") or "")],
        ["企业类型", _text(profile.get("企业类型") or _dict(job.get("工商信息")).get("企业类型"))],
        ["招聘活跃度", _text(profile.get("招聘活跃度") or "")],
    ]
    return {
        "name": _company_name(company_ref, job, company_risk),
        "code": _text(company_id),
        "tags": _company_tags(profile),
        "meta": {
            "size": _text(profile.get("人员规模") or profile.get("参保人数") or ""),
            "stage": _text(profile.get("登记状态") or _dict(job.get("工商信息")).get("经营状态")),
            "founded": founded[:4] if founded else "",
            "location": _location_from_address(_text(job.get("工作地址"))),
        },
        "info": [row for row in info if row[1]],
        "scores": _company_scores(unified, industry_score),
        "desc": _text(company_risk.get("汇总要点") or unified.get("text")),
        "industry": {
            "name": industry_name,
            "score": _score(industry_score.get("分数")),
            "desc": _text(_dict(industry_outlook.get("综合评估")).get("汇总要点") or industry_score.get("text")),
            "metrics": _industry_metrics(industry_score),
        },
    }


def _module_analysis(module: Any) -> dict[str, Any]:
    if isinstance(module, dict) and isinstance(module.get("analysis"), dict):
        return module["analysis"]
    return module if isinstance(module, dict) else {}


def _dimension_scores(
    job_value: dict[str, Any],
    company_risk: dict[str, Any],
    industry_outlook: dict[str, Any],
) -> dict[str, int]:
    job_dims = _dict(job_value.get("维度评分"))
    source = {
        "职责质量": _dict(job_dims.get("职责质量")),
        "要求合理性": _dict(job_dims.get("要求合理性")),
        "薪酬福利": _dict(job_dims.get("薪酬福利")),
        "工作强度": _dict(job_dims.get("工作强度")),
        "统一评分": _dict(company_risk.get("统一评分")),
        "行业评分": _dict(industry_outlook.get("行业评分")),
    }
    return {front_key: _score(source[raw_key].get("分数")) for front_key, _, raw_key in DIMENSION_MAP}


def _dimension_details(
    job_value: dict[str, Any],
    company_risk: dict[str, Any],
    industry_outlook: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    job_dims = _dict(job_value.get("维度评分"))
    source = {
        "职责质量": _dict(job_dims.get("职责质量")),
        "要求合理性": _dict(job_dims.get("要求合理性")),
        "薪酬福利": _dict(job_dims.get("薪酬福利")),
        "工作强度": _dict(job_dims.get("工作强度")),
        "统一评分": _dict(company_risk.get("统一评分")),
        "行业评分": _dict(industry_outlook.get("行业评分")),
    }
    return {
        front_key: {
            "title": _text(source[raw_key].get("title") or name),
            "text": _text(source[raw_key].get("text")),
            "kpis": _kpis(source[raw_key].get("kpis")),
        }
        for front_key, name, raw_key in DIMENSION_MAP
    }


def _job_meta(job: dict[str, Any], job_profile: dict[str, Any]) -> list[dict[str, Any]]:
    meta = [
        {"ico": "location", "label": _text(job.get("职位工作地点") or job_profile.get("工作地点"))},
        {"ico": "salary", "label": _text(job.get("薪资")), "isSalary": True},
        {"ico": "exp", "label": _text(job.get("要求年限") or job_profile.get("经验要求"))},
        {"ico": "edu", "label": _text(job.get("学历要求") or job_profile.get("学历要求"))},
        {"ico": "type", "label": "全职"},
        {"ico": "team", "label": _text(job_profile.get("岗位定位") or _first(_string_list(job_profile.get("关键词"))))},
    ]
    return [item for item in meta if item["label"]]


def _summary_meta(
    job: dict[str, Any],
    company_risk: dict[str, Any],
    industry_outlook: dict[str, Any],
) -> dict[str, str]:
    profile = _dict(company_risk.get("公司画像"))
    return {
        "type": _infer_job_type(_text(job.get("职位名称"))),
        "industry": _industry_name(profile, industry_outlook),
        "edu": _text(job.get("学历要求")),
        "exp": _text(job.get("要求年限")),
        "headcount": "",
        "posted": "",
    }


def _summary(
    final: dict[str, Any],
    job_value: dict[str, Any],
    company_risk: dict[str, Any],
    industry_outlook: dict[str, Any],
) -> list[str]:
    profile = _dict(final.get("岗位画像"))
    recommendation = _dict(final.get("申请建议"))
    pieces = [
        _text(profile.get("一句话总结")),
        _text(recommendation.get("理由")),
        _text(job_value.get("汇总要点")),
        _text(company_risk.get("汇总要点")),
        _text(_dict(industry_outlook.get("综合评估")).get("汇总要点")),
    ]
    return [p for p in pieces if p][:3]


def _company_id(company_ref: dict[str, Any], job: dict[str, Any], company_risk: dict[str, Any]) -> str:
    profile = _dict(company_risk.get("公司画像"))
    return _text(
        company_ref.get("uscc")
        or profile.get("统一社会信用代码")
        or _dict(job.get("工商信息")).get("统一社会信用代码")
        or company_ref.get("company_name")
        or profile.get("公司名称")
        or "unknown-company"
    )


def _company_name(company_ref: dict[str, Any], job: dict[str, Any], company_risk: dict[str, Any]) -> str:
    profile = _dict(company_risk.get("公司画像"))
    return _text(
        company_ref.get("company_name")
        or profile.get("公司名称")
        or _dict(job.get("工商信息")).get("公司名称")
        or "未知公司"
    )


def _company_tags(profile: dict[str, Any]) -> list[str]:
    tags = [
        _text(profile.get("登记状态")),
        _text(profile.get("所属行业")),
        _text(profile.get("招聘活跃度")).split("（", 1)[0],
    ]
    return [tag for tag in tags if tag][:3]


def _company_scores(unified: dict[str, Any], industry_score: dict[str, Any]) -> dict[str, int]:
    scores: dict[str, int] = {}
    company_score = _score(unified.get("分数"))
    outlook_score = _score(industry_score.get("分数"))
    if company_score:
        scores["financialStability"] = company_score
        scores["management"] = company_score
    if outlook_score:
        scores["growth"] = outlook_score
    return scores


def _industry_name(profile: dict[str, Any], industry_outlook: dict[str, Any]) -> str:
    distribution = industry_outlook.get("行业分布")
    if isinstance(distribution, list) and distribution:
        first = _dict(distribution[0])
        if first.get("行业名"):
            return _text(first.get("行业名"))
    return _text(profile.get("所属行业"))


def _industry_metrics(industry_score: dict[str, Any]) -> list[dict[str, str]]:
    return [{"val": _text(k.get("val")), "label": _text(k.get("label"))} for k in _kpis(industry_score.get("kpis"))[:3]]


def _kpis(value: Any) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else []
    kpis = [
        {
            "label": _text(_dict(item).get("label")),
            "val": _text(_dict(item).get("val")),
            "sub": _text(_dict(item).get("sub")),
        }
        for item in items[:4]
    ]
    while len(kpis) < 4:
        kpis.append({"label": "", "val": "", "sub": ""})
    return kpis


def _job_code(url: Any, fallback: str) -> str:
    text = _text(url)
    match = re.search(r"/job_detail/([^/?#]+)", text)
    if match:
        return match.group(1).replace(".html", "")[:12]
    return fallback[:12]


def _mini_label(company_name: str, title: str, job_profile: dict[str, Any], final_profile: dict[str, Any]) -> str:
    keywords = _string_list(job_profile.get("关键词") or final_profile.get("关键词"))
    suffix = _first(keywords) or title
    return f"{company_name} · {suffix}"


def _match_tag(fit: dict[str, Any], total: int) -> str:
    fit_level = _text(fit.get("匹配等级"))
    if fit_level:
        return fit_level
    if total >= 80:
        return "高度匹配"
    if total >= 65:
        return "较匹配"
    return "需评估"


def _tag_text(action: str, score: int) -> str:
    if action in {"立即投递", "强烈推荐"} or score >= 85:
        return "强烈推荐"
    if action in {"重点关注", "推荐投递"} or score >= 70:
        return "推荐投递"
    if action in {"谨慎评估", "谨慎考虑"} or score >= 50:
        return "谨慎考虑"
    return "暂不推荐"


def _action_from_score(score: int) -> str:
    if score >= 80:
        return "立即投递"
    if score >= 65:
        return "重点关注"
    if score >= 40:
        return "谨慎评估"
    return "暂不推荐"


def _grade_letter(score: int) -> str:
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def _badge_cls(score: int) -> str:
    if score >= 80:
        return "badge-green"
    if score >= 65:
        return "badge-orange"
    return "badge-neutral"


def _infer_job_type(title: str) -> str:
    if any(word in title for word in ("前端", "后端", "全栈", "工程师", "开发")):
        return "技术研发"
    if "产品" in title:
        return "产品"
    if "运营" in title:
        return "运营"
    return ""


def _location_from_address(address: str) -> str:
    if not address:
        return ""
    match = re.match(r"([\u4e00-\u9fa5]{2,6}(?:市|区|县)?)", address)
    return match.group(1) if match else address[:8]


def _score(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("分数") or value.get("score")
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    text = _text(value)
    return [text] if text else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _first(values: list[str]) -> str:
    return values[0] if values else ""
