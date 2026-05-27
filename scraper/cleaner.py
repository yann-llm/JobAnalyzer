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

from bs4 import BeautifulSoup

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


def _extract_business_info_from_html(html: str, base_url: str) -> dict[str, Any]:
    if not html:
        return {}

    soup = BeautifulSoup(html, "lxml")
    info: dict[str, Any] = {}
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

    return {
        "url": page.url,
        "final_url": page.final_url,
        "fetched_at": page.fetched_at,
        "page_title": page.title or None,
        "quick_fields": {k: v for k, v in quick_fields.items() if v},
        "business_info": business_info,
        "body_text": body_text,
        "body_truncated": truncated,
        "screenshot_path": page.screenshot_path,
        "meta": page.meta,
    }
