"""Salary benchmark lookup module.

Reads ``external_data/references/hudson_2025_tech.csv`` (Hudson 2025
中国大陆薪酬报告 第 41-43 页 科技/IT 板块) and provides fuzzy lookup by
job role.

**Unit convention:**
- CSV columns ``national_low_k`` / ``national_high_k`` store **annual base
  salary in K RMB (千元)**. Hudson reports use 「千元人民币」 without
  specifying month/year, but cross-referencing with market rates confirms
  these are annual figures (e.g. 350-650 = ¥350-650K/year for full-stack).
- BOSS / Lagou job postings use **monthly K**. We convert to annual by
  multiplying by 13 (default). Override with ``ANNUAL_MONTH_FACTOR`` env
  var if the JD explicitly mentions a different multiplier (e.g. 14, 16).

Usage::

    from external_data.salary_benchmark import lookup_salary, format_kpi

    bench = lookup_salary("AI 全栈工程师")
    # → {'category': 'IT开发与架构', 'role': '全栈程序员',
    #    'annual_low_k': 350, 'annual_high_k': 650, 'source': 'Hudson 2025'}

    kpi = format_kpi(bench, posted_monthly_min=30, posted_monthly_max=45)
    # → {'label': '现金月薪', 'val': '30-45K',
    #    'sub': '基准 27-50K（全栈程序员·Hudson 2025） · 偏上'}
"""

from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

REFERENCE_DIR = Path(__file__).resolve().parent / "references"
HUDSON_CSV = REFERENCE_DIR / "hudson_2025_tech.csv"

# How many months of base salary per year. Default 13 (China common: 12+1
# year-end bonus). Tech industry often uses 14-16.
DEFAULT_MONTHS_PER_YEAR = 13

_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("ai 负责人", "ai负责人", "首席ai", "ai 总监"), "AI负责人"),
    (("ai 产品", "ai产品"), "AI产品经理"),
    (("算法工程师", "ml engineer", "深度学习", "nlp"), "算法工程师"),
    (("数据科学家", "data scientist"), "数据科学家"),
    (("数据架构师",), "数据架构师"),
    (("数据分析师", "数据分析", "数据工程师", "data analyst"), "数据分析师/工程师"),
    (("商业分析经理",), "商业分析经理"),
    (("业务分析师", "business analyst"), "业务分析师"),
    (("软件研发总监",), "软件研发总监"),
    (("软件架构师", "架构师"), "软件架构师"),
    (("软件开发经理", "研发经理", "开发经理", "技术经理"), "软件开发经理"),
    (("高级软件工程师", "高级工程师", "senior software"), "高级软件工程师"),
    (("全栈", "fullstack", "full stack", "full-stack"), "全栈程序员"),
    (("前端", "frontend", "front-end", "react", "vue"), "前端程序员"),
    (("后端", "backend", "back-end", "java 工程师", "python 工程师"), "后端程序员"),
    (("数字化转型负责人",), "数字化转型负责人"),
    (("数字化技术总监",), "数字化技术总监"),
    (("it 总监", "技术总监", "cto"), "IT总监"),
    (("it 项目总监",), "IT项目总监"),
    (("it 项目经理",), "IT项目经理"),
    (("企业架构师",), "企业架构师"),
    (("解决方案架构师",), "解决方案架构师"),
    (("产品负责人",), "产品负责人"),
    (("产品经理",), "产品经理"),
    (("信息安全总监",), "信息安全总监"),
    (("信息安全高级经理",), "信息安全高级经理"),
    (("信息安全经理",), "信息安全经理"),
    (("数据隐私",), "数据隐私官"),
    (("信息安全",), "信息安全专员"),
    (("基础设施总监",), "基础设施总监"),
    (("基础设施架构师",), "基础设施架构师"),
    (("基础设施经理",), "基础设施经理"),
    (("云计算", "kubernetes", "k8s", "云原生"), "云计算工程师"),
    (("网络工程师", "运维工程师", "devops", "sre"), "网络工程师"),
    (("erp 顾问经理", "erp 经理"), "ERP顾问经理"),
    (("erp 顾问", "sap 顾问"), "ERP顾问"),
]


def _months_per_year() -> int:
    raw = os.getenv("SALARY_MONTHS_PER_YEAR")
    try:
        return int(raw) if raw else DEFAULT_MONTHS_PER_YEAR
    except ValueError:
        return DEFAULT_MONTHS_PER_YEAR


@lru_cache(maxsize=1)
def _load_table() -> list[dict[str, Any]]:
    if not HUDSON_CSV.exists():
        return []
    rows: list[dict[str, Any]] = []
    with HUDSON_CSV.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append({
                "category": row["role_category"],
                "role": row["role"],
                "annual_low_k": int(row["national_low_k"]),
                "annual_high_k": int(row["national_high_k"]),
                "source": row["source"],
            })
    return rows


def _normalize(text: str) -> str:
    return (text or "").lower().strip()


def lookup_salary(job_title: str) -> dict[str, Any] | None:
    """Fuzzy-match a job title to a Hudson benchmark row.

    Returns dict with ``annual_low_k`` / ``annual_high_k`` (annual K RMB),
    or None on no match.
    """
    title_norm = _normalize(job_title)
    if not title_norm:
        return None

    table = _load_table()
    if not table:
        return None
    by_role = {row["role"]: row for row in table}

    for keywords, role_name in _ALIASES:
        if any(kw in title_norm for kw in keywords):
            row = by_role.get(role_name)
            if row:
                return row

    for row in table:
        if _normalize(row["role"]) in title_norm:
            return row

    return None


def parse_posted_salary(salary_str: str) -> tuple[int | None, int | None]:
    """Parse a posted salary string (monthly K) like '30-45K' or '30k-50k·14薪'.

    Returns (monthly_min_k, monthly_max_k) or (None, None) on failure.
    """
    import re
    if not salary_str:
        return (None, None)
    s = salary_str.lower().replace(" ", "")
    m = re.search(r"(\d+)k?[-~](\d+)k", s)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r"(\d+)k", s)
    if m:
        v = int(m.group(1))
        return (v, v)
    return (None, None)


def annual_to_monthly_range(
    annual_low_k: int,
    annual_high_k: int,
    months: int | None = None,
) -> tuple[int, int]:
    """Convert annual K range to monthly K range using months-per-year factor."""
    m = months or _months_per_year()
    return (round(annual_low_k / m), round(annual_high_k / m))


def format_kpi(
    benchmark: dict[str, Any] | None,
    posted_monthly_min: int | None = None,
    posted_monthly_max: int | None = None,
) -> dict[str, str]:
    """Build {label, val, sub} for the salary KPI card.

    Output style matches ``data.txt`` convention:
    - ``val``: the posted salary range (key value)
    - ``sub``: benchmark comparison (or '基准未匹配' / 'JD 未提供薪资')
    All values are in monthly K. The benchmark is converted from annual.
    """
    if posted_monthly_min is not None and posted_monthly_max is not None:
        val = f"{posted_monthly_min}-{posted_monthly_max}K"
    elif posted_monthly_min is not None:
        val = f"{posted_monthly_min}K"
    else:
        val = "未提供"

    if benchmark is None:
        sub = "基准未匹配（JD 职位类目不在 Hudson 2025 科技报告内）"
    else:
        bm_lo_m, bm_hi_m = annual_to_monthly_range(
            benchmark["annual_low_k"], benchmark["annual_high_k"]
        )
        role = benchmark["role"]
        src = benchmark["source"]
        position = ""
        if posted_monthly_min is not None and posted_monthly_max is not None:
            posted_mid = (posted_monthly_min + posted_monthly_max) / 2
            bm_mid = (bm_lo_m + bm_hi_m) / 2
            if posted_mid >= bm_hi_m:
                position = "高于基准"
            elif posted_mid <= bm_lo_m:
                position = "低于基准"
            elif posted_mid >= bm_mid:
                position = "区间偏上"
            else:
                position = "区间偏下"
        # sub: benchmark range + role + source + verdict
        if position:
            sub = f"{bm_lo_m}-{bm_hi_m}K（{role} · {src}） · {position}"
        else:
            sub = f"{bm_lo_m}-{bm_hi_m}K（{role} · {src}）"

    return {"label": "现金月薪", "val": val, "sub": sub}


def benchmark_summary() -> dict[str, Any]:
    table = _load_table()
    return {
        "loaded": bool(table),
        "rows": len(table),
        "source_csv": str(HUDSON_CSV),
        "categories": sorted({r["category"] for r in table}),
        "months_per_year": _months_per_year(),
    }
