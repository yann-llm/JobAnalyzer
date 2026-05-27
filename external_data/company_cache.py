"""On-disk cache for QCC company data, keyed by USCC.

QCC tools return relatively stable data (registration info changes weekly,
risk data updates daily). Caching by 统一社会信用代码 lets us avoid 8 MCP
calls when the same company appears across multiple job postings.

Cache layout::

    data/_company_cache/
        914201005655891077.json   # one file per USCC

Each file holds the full ``qcc_block`` (anchor + company + risk + cleaned)
plus a ``cached_at`` ISO timestamp used for TTL checks.

TTL is controlled by ``QCC_CACHE_TTL_DAYS`` env var:

  * unset or > 0 → that many days (default 7)
  * 0 or negative → cache disabled (always miss)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CACHE_DIR_NAME = "_company_cache"
DEFAULT_TTL_DAYS = 7
TTL_ENV = "QCC_CACHE_TTL_DAYS"

# USCC: 18 chars, uppercase letters and digits.
_USCC_RE = re.compile(r"^[0-9A-Z]{18}$")


def _ttl_days() -> int:
    raw = os.getenv(TTL_ENV)
    if raw is None or raw == "":
        return DEFAULT_TTL_DAYS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_TTL_DAYS


def _is_valid_uscc(uscc: str) -> bool:
    return bool(uscc) and bool(_USCC_RE.match(uscc))


def cache_path(data_root: Path, uscc: str) -> Path:
    return data_root / CACHE_DIR_NAME / f"{uscc}.json"


def load_cached(data_root: Path, uscc: str) -> dict[str, Any] | None:
    """Return cached qcc_block if present and not expired, else None."""
    ttl_days = _ttl_days()
    if ttl_days <= 0:
        return None
    if not _is_valid_uscc(uscc):
        return None

    path = cache_path(data_root, uscc)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    cached_at_str = payload.get("cached_at")
    if not cached_at_str:
        return None
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
    except ValueError:
        return None

    age = datetime.now(timezone.utc) - cached_at
    if age > timedelta(days=ttl_days):
        return None

    block = payload.get("qcc_block")
    if not isinstance(block, dict):
        return None
    return block


def save_cached(data_root: Path, uscc: str, qcc_block: dict[str, Any]) -> None:
    """Persist qcc_block to disk under USCC. Best-effort; failures are silent."""
    if _ttl_days() <= 0:
        return
    if not _is_valid_uscc(uscc):
        return
    if qcc_block.get("status") != "ok":
        return  # only cache successful fetches

    path = cache_path(data_root, uscc)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "uscc": uscc,
            "qcc_block": qcc_block,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
