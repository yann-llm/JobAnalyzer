"""LLM analyzer orchestration and related analysis input loading."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from pipeline.job_data import DATA_DIR, PROJECT_DIR, ProgressCallback, emit_progress, isoformat, now_utc, write_json


def load_company_cleaned(base_dir: Path) -> dict[str, Any] | None:
    """Resolve `company.json` to the cleaned company data (with industry_data merged in)."""
    ref_path = base_dir / "company.json"
    if not ref_path.exists():
        return None
    try:
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if ref.get("status") != "ok":
        return None
    cache_rel = ref.get("cache_path")
    if not cache_rel:
        return None
    cache_path = DATA_DIR / cache_rel
    if not cache_path.exists():
        print(f"[分析] 公司缓存缺失: {cache_path}")
        return None
    try:
        cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    block = cache_payload.get("qcc_block") or {}
    cleaned = dict(block.get("cleaned") or {})
    industry_data = block.get("industry_data")
    if industry_data:
        cleaned["industry_data"] = industry_data
    return cleaned or None


def load_candidate_profile() -> dict[str, Any] | None:
    """Load candidate profile from project root, returning None when missing/invalid."""
    profile_path = PROJECT_DIR / "candidate_profile.json"
    if not profile_path.exists():
        return None
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[分析] candidate_profile.json 解析失败: {exc}")
        return None
    if not isinstance(data, dict):
        return None
    return data


def inject_salary_benchmark(
    job_value_module: dict[str, Any] | None,
    job_cleaned: dict[str, Any],
) -> None:
    """Replace LLM-generated salary KPI with Hudson 2025 benchmark lookup."""
    if not job_value_module or job_value_module.get("status") == "error":
        return
    try:
        from external_data.salary_benchmark import (
            format_kpi,
            lookup_salary,
            parse_posted_salary,
        )

        analysis = job_value_module.get("analysis") or {}
        pay_dim = (analysis.get("维度评分") or {}).get("薪酬福利")
        if not isinstance(pay_dim, dict):
            return
        kpis = pay_dim.get("kpis")
        if not isinstance(kpis, list):
            return

        title = job_cleaned.get("职位名称") or ""
        salary = job_cleaned.get("薪资") or ""
        bench = lookup_salary(title)
        lo, hi = parse_posted_salary(salary)
        if lo is None and hi is None:
            return

        new_kpi = format_kpi(bench, lo, hi)
        new_kpi["source"] = "Hudson 2025" if bench else "JD原文"

        for i, k in enumerate(kpis):
            label = (k.get("label") or "") if isinstance(k, dict) else ""
            if any(t in label for t in ("月薪", "薪资", "现金", "年包", "包")):
                kpis[i] = new_kpi
                print(f"  [分析] 注入薪酬基准: {new_kpi['val']} | {new_kpi['sub']}")
                return
        kpis.insert(0, new_kpi)
        print(f"  [分析] 追加薪酬基准 KPI: {new_kpi['val']} | {new_kpi['sub']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [分析] 薪酬基准注入失败（已跳过）: {type(exc).__name__}: {exc}")


def run_analyzers(
    url: str,
    base_dir: Path,
    job_cleaned: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any] | None:
    """Run all analyzers and persist ``analysis.json``."""
    try:
        from analyzers import ANALYZER_REGISTRY, run_analyzer
        from analyzers.final_evaluation_agent import analyze_final_evaluation
    except ImportError as exc:
        print(f"[分析] 分析器模块加载失败，跳过: {exc}")
        return None

    company_cleaned = load_company_cleaned(base_dir)
    candidate_profile = load_candidate_profile()

    print(
        f"[分析] 启动 LLM 分析（公司数据: "
        f"{'有' if company_cleaned else '无'}, 候选人画像: "
        f"{'有' if candidate_profile else '无'}）"
    )

    analyzer_progress = {
        "job_value": ("职位综合价值", 70),
        "company_risk": ("公司风险", 80),
        "industry_outlook": ("行业前景", 88),
    }

    def run_one(name: str, analyzer_fn: Callable[..., dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        print(f"  [分析] 运行 {name}...")
        label, percent = analyzer_progress.get(name, (name, 75))
        emit_progress(
            progress_callback,
            "analyzing",
            f"LLM 分析：{label}",
            percent,
            detail=name,
        )
        try:
            result = run_analyzer(
                analyzer_fn,
                job_cleaned,
                qcc_cleaned=company_cleaned,
                candidate_profile=candidate_profile,
            )
            return name, result
        except Exception as exc:  # noqa: BLE001
            print(f"  [分析] {name} 失败: {type(exc).__name__}: {exc}")
            return name, {
                "module": name,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    module_analyses: dict[str, Any] = {}
    analyzer_items = list(ANALYZER_REGISTRY.items())
    with ThreadPoolExecutor(max_workers=len(analyzer_items) or 1) as executor:
        futures = {
            executor.submit(run_one, name, analyzer_fn): name
            for name, analyzer_fn in analyzer_items
        }
        for future in as_completed(futures):
            name, result = future.result()
            module_analyses[name] = result

    module_analyses = {
        name: module_analyses[name]
        for name in ANALYZER_REGISTRY
        if name in module_analyses
    }

    inject_salary_benchmark(module_analyses.get("job_value"), job_cleaned)

    print("  [分析] 运行 final_evaluation...")
    emit_progress(
        progress_callback,
        "analyzing",
        "LLM 分析：综合评估",
        95,
        detail="final_evaluation",
    )
    try:
        final = analyze_final_evaluation(url, module_analyses, candidate_profile)
    except Exception as exc:  # noqa: BLE001
        print(f"  [分析] final_evaluation 失败: {type(exc).__name__}: {exc}")
        final = {
            "module": "final_evaluation",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    bundle = {
        "url": url,
        "generated_at": isoformat(now_utc()),
        "candidate_profile_used": bool(candidate_profile),
        "modules": module_analyses,
        "final": final,
    }
    write_json(base_dir / "analysis.json", bundle)
    return bundle
