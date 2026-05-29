"""Clean a scraped job page into a structured payload for LLM analyzers.

The cleaner is deliberately conservative: it removes scripts/styles, collapses
whitespace, runs a small set of regex-based field guesses (title / company /
location / salary), and exposes the full body text so downstream LLM agents
can still consult the original wording.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString

from .job_scraper import JobPageContent

MAX_TEXT_CHARS = 20_000  # cap to keep prompts within token budget

# Loose patterns — most Chinese & English job sites surface these tokens
# somewhere in the page body. We capture only short snippets so the LLM can
# still rely on the full text for nuance.
_SALARY_RE = re.compile(
    r"(?P<salary>(?:\d{1,3}(?:[,.]\d{3})*|\d+)\s*(?:[Kk万元]|千|万|RMB|USD|CNY|元)?\s*(?:[-–~至]|to)\s*(?:\d{1,3}(?:[,.]\d{3})*|\d+)\s*(?:[Kk万元]|千|万|RMB|USD|CNY|元))"
)
_YEARS_RE = re.compile(r"(?P<years>\d+\s*[-~至]\s*\d+\s*年|\d+\s*年(?:以上|以下)?|应届(?:生)?)")
_EDU_KEYWORDS = ("博士", "硕士", "本科", "大专", "中专", "高中", "PhD", "Master", "Bachelor", "学历不限")
_LOCATION_RE = re.compile(r"(工作地点|地点|城市|Location)[：: ]\s*([^\n，,；;]{1,40})")
_COMPANY_RE = re.compile(r"(公司|Company)[：: ]\s*([^\n，,；;]{1,60})")
_USCC_RE = re.compile(r"(?<![0-9A-Z])([0-9A-Z]{18})(?![0-9A-Z])")
_USCC_ALPHABET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

_BUSINESS_LABELS = {
    "company_name": ("公司名称", "企业名称"),
    "unified_social_credit_code": ("统一社会信用代码", "统一社会信用代码/注册号", "信用代码"),
    "legal_representative": ("法定代表人", "法人代表"),
    "established_date": ("成立日期",),
    "company_type": ("企业类型", "公司类型"),
    "business_status": ("经营状态", "登记状态"),
    "registered_capital": ("注册资金", "注册资本"),
}
_SECTION_HEADINGS = (
    "职位描述",
    "岗位职责",
    "工作职责",
    "任职要求",
    "职位要求",
    "必须具备",
    "加分项",
    "不适合的人",
    "岗位福利",
    "公司介绍",
    "工商信息",
    "工作地址",
    "竞争力分析",
    "更多职位",
    "精选职位",
    "看过该职位的人还看了",
    "BOSS 安全提示",
)


def _normalize_whitespace(text: str) -> str:
    # Collapse runs of whitespace but keep paragraph breaks.
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return _normalize_whitespace(soup.get_text("\n"))


def _first_match(pattern: re.Pattern[str], text: str, group: int | str = 0) -> str | None:
    m = pattern.search(text)
    if not m:
        return None
    try:
        return m.group(group).strip()
    except (IndexError, KeyError):
        return None


def _guess_education(text: str) -> str | None:
    # Look in the first ~2000 chars to bias towards header/summary sections.
    head = text[:2000]
    for kw in _EDU_KEYWORDS:
        if kw in head:
            return kw
    return None


def _guess_field(regex: re.Pattern[str], text: str, group: int) -> str | None:
    m = regex.search(text)
    if not m:
        return None
    return m.group(group).strip()


def _compact_label_value_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _normalize_uscc(value: str | None) -> str | None:
    if not value:
        return None
    match = _USCC_RE.search(value.upper())
    if not match:
        return None
    code = match.group(1)
    if any(ch not in _USCC_ALPHABET for ch in code):
        return None
    total = sum(_USCC_ALPHABET.index(ch) * weight for ch, weight in zip(code[:17], _USCC_WEIGHTS))
    check_code = _USCC_ALPHABET[(31 - total % 31) % 31]
    return code if code[-1] == check_code else None


def _extract_after_label(text: str, labels: tuple[str, ...], max_chars: int = 80) -> str | None:
    compact = _compact_label_value_text(text)
    for label in labels:
        idx = compact.find(label)
        if idx < 0:
            continue
        start = idx + len(label)
        tail = compact[start:start + max_chars]
        for prefix in ("/注册号", "注册号"):
            if tail.startswith(prefix):
                tail = tail[len(prefix):]
        for stop in (
            "统一社会信用代码",
            "信用代码",
            "公司名称",
            "企业名称",
            "法定代表人",
            "法人代表",
            "成立日期",
            "企业类型",
            "公司类型",
            "经营状态",
            "登记状态",
            "注册资金",
            "注册资本",
            "注册地址",
            "经营范围",
            "查看全部",
        ):
            pos = tail.find(stop)
            if pos > 0:
                tail = tail[:pos]
        value = tail.strip("：:，,；; ")
        if value:
            return value
    return None


def _field_value(key: str, value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if key == "unified_social_credit_code":
        return _normalize_uscc(value)
    return value


def _extract_business_info_from_text(text: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]

    for idx, line in enumerate(lines):
        for key, labels in _BUSINESS_LABELS.items():
            if line in labels and idx + 1 < len(lines):
                value = _field_value(key, lines[idx + 1])
                if value and value not in _BUSINESS_LABELS:
                    info.setdefault(key, value)

    for key, labels in _BUSINESS_LABELS.items():
        info.setdefault(key, _field_value(key, _extract_after_label(text, labels)))

    if "信用代码" in (text or "") or "统一社会信用代码" in (text or ""):
        for uscc_match in _USCC_RE.finditer((text or "").upper()):
            uscc = _normalize_uscc(uscc_match.group(1))
            if uscc:
                info["unified_social_credit_code"] = uscc
                break

    return {k: v for k, v in info.items() if v}


def _map_business_label(label_text: str) -> str | None:
    label = _compact_label_value_text(label_text).strip("：:")
    for key, labels in _BUSINESS_LABELS.items():
        if label in labels:
            return key
    return None


def _collect_labeled_html_fields(root: Any) -> dict[str, str]:
    info: dict[str, str] = {}

    for item in root.select("li"):
        label = item.find("span")
        if not label:
            continue
        key = _map_business_label(label.get_text(" ", strip=True))
        if not key:
            continue
        value = item.get_text(" ", strip=True).replace(label.get_text(" ", strip=True), "", 1).strip()
        value = _field_value(key, value)
        if value:
            info[key] = value

    for row in root.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        for idx in range(len(cells) - 1):
            key = _map_business_label(cells[idx])
            value = _field_value(key or "", cells[idx + 1])
            if key and value:
                info[key] = value

    for label in root.select("dt, .label, .name, .info-label, .business-label"):
        key = _map_business_label(label.get_text(" ", strip=True))
        if not key:
            continue
        value_node = label.find_next_sibling(["dd", "span", "p", "div"])
        value = _field_value(key, value_node.get_text(" ", strip=True) if value_node else "")
        if value:
            info[key] = value

    return info


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _extract_section_text(
    body_text: str,
    start_labels: tuple[str, ...],
    stop_labels: tuple[str, ...] = _SECTION_HEADINGS,
) -> str | None:
    lines = _lines(body_text)
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if line in start_labels:
            start_idx = idx + 1
            break
    if start_idx is None:
        return None
    values: list[str] = []
    for offset, line in enumerate(lines[start_idx:]):
        if line in stop_labels and values:
            break
        next_line = lines[start_idx + offset + 1] if start_idx + offset + 1 < len(lines) else ""
        if values and ("活跃" in next_line or next_line in {"HR", "人事", "招聘者"}):
            break
        if line in {"查看全部", "展开", "点击查看地图", "微信扫码分享 举报"}:
            continue
        values.append(line)
    return _normalize_whitespace("\n".join(values)) if values else None


def _extract_title_salary_location_from_header(body_text: str) -> dict[str, str | None]:
    lines = _lines(body_text)
    info: dict[str, str | None] = {"job_title": None, "salary": None, "job_location": None}
    for idx, line in enumerate(lines[:40]):
        salary = _first_match(_SALARY_RE, line, "salary")
        if not salary:
            continue
        title = line.replace(salary, "").strip(" -_｜|")
        info["job_title"] = title or None
        info["salary"] = salary
        if idx + 1 < len(lines):
            parts = lines[idx + 1].split()
            if parts:
                info["job_location"] = parts[0]
        break
    return info


def _extract_job_address(body_text: str) -> str | None:
    text = _extract_section_text(body_text, ("工作地址",), ("更多职位", "精选职位", "看过该职位的人还看了", "BOSS 安全提示"))
    if not text:
        return None
    lines = [line for line in _lines(text) if line != "点击查看地图"]
    return "\n".join(lines) if lines else None


def _extract_job_description_from_html(html: str) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    candidates = [
        soup.select_one(".job-detail-section .job-sec-text"),
        soup.select_one(".job-detail-section .job-sec-text.fold-text"),
        soup.select_one(".job-sec-text"),
    ]
    for node in candidates:
        if node:
            text = _normalize_whitespace(node.get_text("\n", strip=True))
            if text:
                return text
    return None


def _business_info_chinese(info: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "company_name": "公司名称",
        "unified_social_credit_code": "统一社会信用代码",
        "legal_representative": "法定代表人",
        "established_date": "成立日期",
        "company_type": "企业类型",
        "business_status": "经营状态",
        "registered_capital": "注册资金",
        "company_detail_url": "公司详情页",
    }
    return {label: info[key] for key, label in mapping.items() if info.get(key)}


def _clean_page_content(page: JobPageContent, body_text: str, quick_fields: dict[str, Any], business_info: dict[str, Any]) -> dict[str, Any]:
    header = _extract_title_salary_location_from_header(body_text)
    requirements_line = None
    if header.get("job_location"):
        for line in _lines(body_text)[:50]:
            if header["job_location"] and line.startswith(str(header["job_location"])):
                requirements_line = line
                break
    requirement_parts = requirements_line.split() if requirements_line else []

    return {
        "职位名称": header.get("job_title") or quick_fields.get("title") or page.title or None,
        "薪资": header.get("salary") or quick_fields.get("salary"),
        "职位工作地点": header.get("job_location") or quick_fields.get("location"),
        "要求年限": quick_fields.get("experience") or (requirement_parts[1] if len(requirement_parts) > 1 else None),
        "学历要求": quick_fields.get("education") or (requirement_parts[2] if len(requirement_parts) > 2 else None),
        "职位描述": _extract_section_text(
            body_text,
            ("职位描述",),
            ("竞争力分析", "BOSS 安全提示", "公司介绍", "工商信息", "工作地址", "更多职位", "精选职位", "看过该职位的人还看了"),
        ),
        "工商信息": _business_info_chinese(business_info),
        "工作地址": _extract_job_address(body_text),
    }


def _extract_business_info_from_html(html: str, base_url: str) -> dict[str, Any]:
    if not html:
        return {}

    soup = BeautifulSoup(html, "lxml")
    info: dict[str, Any] = {}
    header_company_name = _extract_company_header_name(soup)
    if header_company_name:
        info["company_header_name"] = header_company_name
        info["company_name"] = header_company_name

    box = soup.select_one(".business-info-box") or soup.find(
        lambda tag: tag.name in {"div", "section"} and "工商信息" in tag.get_text(" ", strip=True)[:80]
    )
    if box:
        info.update(_collect_labeled_html_fields(box))

        detail_link = box.select_one('a.look-all[href*="/gongsi/"]') or box.select_one('a[href*="/gongsi/"]')
        if detail_link and detail_link.get("href"):
            info["company_detail_url"] = urljoin(base_url, detail_link["href"])

    info.update({k: v for k, v in _collect_labeled_html_fields(soup).items() if k not in info})

    if "company_detail_url" not in info:
        link = soup.select_one('a[ka="job-detail-company_custompage"][href*="/gongsi/"]')
        if link and link.get("href"):
            info["company_detail_url"] = urljoin(base_url, link["href"])

    text_info = _extract_business_info_from_text(soup.get_text("\n"))
    return {**text_info, **info}


def _extract_company_header_name(soup: BeautifulSoup) -> str | None:
    if not (
        soup.select_one("body.company-body-wrapper")
        or soup.select_one("#main.company-new")
        or soup.select_one(".company-new .company-banner")
    ):
        return None

    selectors = (
        "#main.company-new .company-banner .company-info h1.name",
        "#main.company-new .company-banner h1.name",
        ".company-new .company-banner .company-info h1.name",
        ".company-new .company-banner h1.name",
        ".company-banner .company-info h1.name",
        ".company-banner h1.name",
    )
    for selector in selectors:
        for node in soup.select(selector):
            name = _company_name_text_from_node(node)
            if name:
                return name
    return None


def _company_name_text_from_node(node: Any) -> str | None:
    direct_text = " ".join(
        str(child).strip()
        for child in node.children
        if isinstance(child, NavigableString) and str(child).strip()
    )
    if direct_text:
        return _normalize_whitespace(direct_text).strip("：:，,；; |｜-") or None

    for child in node.find_all(recursive=False):
        classes = set(child.get("class") or [])
        if child.name in {"a", "button"} or classes & {"btn", "op", "action", "follow", "collect"}:
            continue
        text = _normalize_whitespace(child.get_text(" ", strip=True)).strip("：:，,；; |｜-")
        if text:
            return text
    return None


def clean_job_page(page: JobPageContent) -> dict[str, Any]:
    """Return a structured cleaned payload from a scraped page.

    The returned dict is intentionally JSON-serializable — every analyzer
    consumes it as plain data.
    """
    body_text = page.text.strip() if page.text else ""
    if not body_text and page.html:
        body_text = _extract_visible_text(page.html)
    body_text = _normalize_whitespace(body_text)

    truncated = False
    if len(body_text) > MAX_TEXT_CHARS:
        body_text = body_text[:MAX_TEXT_CHARS]
        truncated = True

    quick_fields: dict[str, Any] = {
        "title": page.title or None,
        "salary": _first_match(_SALARY_RE, body_text, "salary"),
        "experience": _first_match(_YEARS_RE, body_text, "years"),
        "education": _guess_education(body_text),
        "location": _guess_field(_LOCATION_RE, body_text, 2),
        "company": _guess_field(_COMPANY_RE, body_text, 2),
    }
    business_info = {
        **_extract_business_info_from_text(body_text),
        **_extract_business_info_from_html(page.html or "", page.final_url or page.url),
    }
    job_description = _extract_job_description_from_html(page.html or "") or _extract_section_text(
        body_text,
        ("职位描述",),
        ("竞争力分析", "BOSS 安全提示", "公司介绍", "工商信息", "工作地址", "更多职位", "精选职位", "看过该职位的人还看了"),
    )
    page_content = _clean_page_content(page, body_text, quick_fields, business_info)
    if job_description:
        page_content["职位描述"] = job_description

    return {
        "url": page.url,
        "final_url": page.final_url,
        "fetched_at": page.fetched_at,
        "page_title": page.title or None,
        "page_content": page_content,
        "quick_fields": {k: v for k, v in quick_fields.items() if v},
        "business_info": business_info,
        "body_text": body_text,
        "body_truncated": truncated,
        "screenshot_path": page.screenshot_path,
        "meta": page.meta,
    }
