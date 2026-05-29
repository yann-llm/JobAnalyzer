"""FastAPI entrypoint for the local job analysis frontend."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from main import analyze_url
from pipeline.job_data import slugify_url
from web.adapters import DATA_DIR, PROJECT_DIR, build_company, build_job_analysis, result_dirs, read_json

app = FastAPI(title="Job Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4200", "http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TASKS: dict[str, dict[str, Any]] = {}


class AnalyzeRequest(BaseModel):
    url: str


class ReanalyzeRequest(BaseModel):
    url: str | None = None


@app.get("/api/results")
def list_results() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for result_dir in result_dirs():
        try:
            items.append(build_job_analysis(result_dir.name, include_details=False))
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return items


@app.get("/api/results/{result_id:path}")
def get_result(result_id: str) -> dict[str, Any]:
    try:
        return build_job_analysis(result_id, include_details=True)
    except FileNotFoundError as exc:
        partial_dir = DATA_DIR / result_id
        if partial_dir.is_dir():
            raise HTTPException(status_code=409, detail="analysis not ready") from exc
        raise HTTPException(status_code=404, detail="not found") from exc


@app.get("/api/companies/{company_id:path}")
def get_company(company_id: str) -> dict[str, Any]:
    company = build_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="not found")
    return company


@app.post("/api/analyze", status_code=status.HTTP_202_ACCEPTED)
def submit_analysis(payload: AnalyzeRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    return _create_analysis_task(background_tasks, payload.url, refresh_analysis=False)


@app.post("/api/results/{result_id:path}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
def reanalyze_result(
    result_id: str,
    background_tasks: BackgroundTasks,
    payload: ReanalyzeRequest | None = None,
) -> dict[str, str]:
    url = (payload.url if payload else None) or _url_for_result(result_id)
    if not url:
        raise HTTPException(status_code=404, detail="not found")
    return _create_analysis_task(background_tasks, url, refresh_analysis=True)


@app.get("/api/analyze/{task_id}/stream")
async def stream_progress(task_id: str) -> StreamingResponse:
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="not found")

    async def events():
        next_index = 0
        while True:
            task = TASKS[task_id]
            queued_events = task.get("events") or []
            while next_index < len(queued_events):
                payload = queued_events[next_index]
                next_index += 1
                encoded = json.dumps(payload, ensure_ascii=False)
                if payload["stage"] == "done":
                    yield f"event: done\ndata: {encoded}\n\n"
                    return
                yield f"data: {encoded}\n\n"
                if payload["stage"] == "error":
                    return

            if task.get("stage") == "error":
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/candidate-profile")
def get_candidate_profile() -> Any:
    path = PROJECT_DIR / "candidate_profile.json"
    if not path.exists():
        return Response(content="null", media_type="application/json")
    return read_json(path)


@app.put("/api/candidate-profile")
def update_candidate_profile(profile: dict[str, Any]) -> dict[str, bool]:
    path = PROJECT_DIR / "candidate_profile.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


def _create_analysis_task(
    background_tasks: BackgroundTasks,
    url: str,
    *,
    refresh_analysis: bool,
) -> dict[str, str]:
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {
        "stage": "launching_chrome",
        "message": "准备启动分析任务",
        "percent": 0,
        "url": url,
        "done": False,
        "error": None,
        "slug": slugify_url(url),
        "refreshAnalysis": refresh_analysis,
        "events": [],
    }
    background_tasks.add_task(_run_analysis_task, task_id, url, refresh_analysis)
    return {"taskId": task_id}


def _url_for_result(result_id: str) -> str | None:
    analysis_path = DATA_DIR / result_id / "analysis.json"
    if not analysis_path.exists():
        return None
    try:
        analysis = read_json(analysis_path)
    except (json.JSONDecodeError, OSError):
        return None
    url = analysis.get("url")
    return url if isinstance(url, str) and url else None


def _run_analysis_task(task_id: str, url: str, refresh_analysis: bool = False) -> None:
    task = TASKS[task_id]

    def update_progress(event: dict[str, Any]) -> None:
        _record_task_event(task, event)

    try:
        result = analyze_url(url, progress_callback=update_progress, refresh_analysis=refresh_analysis)
        summary = result.get("summary") or {}
        if summary.get("status") != "success":
            detail = task.get("detail") or _failure_detail_for_summary(summary)
            _record_task_event(task, {
                "stage": "error",
                "message": summary.get("message") or "分析失败",
                "percent": task.get("percent", 0),
                "detail": detail,
            })
            return
        slug = Path(summary.get("output_dir") or DATA_DIR / slugify_url(url)).name
        if not (DATA_DIR / slug / "analysis.json").exists():
            _record_task_event(task, {
                "stage": "error",
                "message": "分析产物缺失，无法展示报告",
                "percent": 100,
                "detail": "analysis_missing",
            })
            return
        _record_task_event(task, {"stage": "done", "message": "分析完成", "percent": 100, "slug": slug})
        task["done"] = True
    except Exception as exc:  # noqa: BLE001
        _record_task_event(task, {
            "stage": "error",
            "message": f"分析失败：{type(exc).__name__}: {exc}",
            "percent": 100,
        })
        task["error"] = str(exc)


def _record_task_event(task: dict[str, Any], event: dict[str, Any]) -> None:
    payload = {
        "stage": event.get("stage", task.get("stage", "analyzing")),
        "message": event.get("message", task.get("message", "")),
        "percent": event.get("percent", task.get("percent", 0)),
    }
    if event.get("detail"):
        payload["detail"] = event["detail"]
    if event.get("slug"):
        payload["slug"] = event["slug"]
    task.update(
        stage=payload["stage"],
        message=payload["message"],
        percent=payload["percent"],
        detail=payload.get("detail"),
    )
    if payload.get("slug"):
        task["slug"] = payload["slug"]
    task.setdefault("events", []).append(payload)


def _failure_detail_for_summary(summary: dict[str, Any]) -> str:
    company = summary.get("company_enrichment") if isinstance(summary.get("company_enrichment"), dict) else {}
    company_status = company.get("status")
    if company_status in {"uscc_unresolved", "no_company_name"}:
        return "company_uscc_unresolved"
    if summary.get("status") == "analysis_error":
        return "analysis_failed"
    return str(summary.get("status") or "error")
