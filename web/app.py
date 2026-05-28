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

from main import analyze_url, slugify_url
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
        raise HTTPException(status_code=404, detail="not found") from exc


@app.get("/api/companies/{company_id:path}")
def get_company(company_id: str) -> dict[str, Any]:
    company = build_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="not found")
    return company


@app.post("/api/analyze", status_code=status.HTTP_202_ACCEPTED)
def submit_analysis(payload: AnalyzeRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {
        "stage": "launching_chrome",
        "message": "准备启动分析任务",
        "percent": 0,
        "url": payload.url,
        "done": False,
        "error": None,
        "slug": slugify_url(payload.url),
    }
    background_tasks.add_task(_run_analysis_task, task_id, payload.url)
    return {"taskId": task_id}


@app.get("/api/analyze/{task_id}/stream")
async def stream_progress(task_id: str) -> StreamingResponse:
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="not found")

    async def events():
        last_payload = None
        while True:
            task = TASKS[task_id]
            payload = {
                "stage": task.get("stage", "analyzing"),
                "message": task.get("message", ""),
                "percent": task.get("percent", 0),
            }
            if task.get("detail"):
                payload["detail"] = task["detail"]
            if task.get("stage") == "done":
                payload["slug"] = task.get("slug")
            if task.get("stage") == "error" and task.get("detail"):
                payload["detail"] = task["detail"]

            encoded = json.dumps(payload, ensure_ascii=False)
            if encoded != last_payload:
                if payload["stage"] == "done":
                    yield f"event: done\ndata: {encoded}\n\n"
                    break
                yield f"data: {encoded}\n\n"
                last_payload = encoded

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


def _run_analysis_task(task_id: str, url: str) -> None:
    task = TASKS[task_id]

    def update_progress(event: dict[str, Any]) -> None:
        task.update(
            stage=event.get("stage", task.get("stage", "analyzing")),
            message=event.get("message", task.get("message", "")),
            percent=event.get("percent", task.get("percent", 0)),
            detail=event.get("detail"),
        )
        if event.get("slug"):
            task["slug"] = event["slug"]

    try:
        result = analyze_url(url, progress_callback=update_progress)
        summary = result.get("summary") or {}
        if summary.get("status") != "success":
            task.update(
                stage="error",
                message=summary.get("message") or "分析失败",
                percent=100,
                detail=summary.get("status"),
            )
            return
        slug = Path(summary.get("output_dir") or DATA_DIR / slugify_url(url)).name
        task.update(stage="done", message="分析完成", percent=100, done=True, slug=slug)
    except Exception as exc:  # noqa: BLE001
        task.update(stage="error", message=f"分析失败：{type(exc).__name__}: {exc}", percent=100, error=str(exc))
