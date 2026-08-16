"""专利检索路由（/projects/{pid}/patents/*）。

对接智慧芽 PatSnap（无 key 时走 Mock 桩），检索结果存 Project.prior_art_refs。
新颖性评估（/assess）：基于检索快照 + 核心章节，chat 强模型流式生成报告，
完成时持久化到 prior_art_refs.assessment。
"""
import time

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import AI_LIMIT, _user_or_ip_key, limiter
from app.deps import get_current_user
from app.models import User
from app.services import patent_service
from app.services.novelty_service import (
    build_assessment_messages,
    load_assessment_context,
    persist_assessment,
)

router = APIRouter(tags=["patents"])


class SearchRequest(BaseModel):
    """专利检索请求。"""
    query: str = Field(..., min_length=1, max_length=500)


class AssessRequest(BaseModel):
    """新颖性评估请求。chat_source 与其它 AI 端点同协议。"""
    chat_source: str | None = None


@router.post("/projects/{project_id}/patents/search")
def search_patents(
    project_id: str,
    payload: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检索现有技术专利，结果持久化到项目 prior_art_refs。"""
    return patent_service.search_prior_art(
        db, user_id=current_user.id, project_id=project_id, query=payload.query,
    )


@router.get("/projects/{project_id}/patents")
def get_patents(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """读取已存的检索结果。无记录返回 null。"""
    return patent_service.get_prior_art(
        db, user_id=current_user.id, project_id=project_id,
    )


@router.post("/projects/{project_id}/patents/assess")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def assess_novelty(
    request: Request,
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    payload: AssessRequest | None = Body(default=None),
):
    """AI 新颖性评估（SSE 流式）：对比文件 × 交底书核心章节 → 结构化报告。

    未检索过对比文件 → 409 引导先检索；核心章节全空 → 409。
    完成时持久化 prior_art_refs.assessment 并在 done 事件回传全文。
    """
    import json

    from app.ai.llm_client import astream_llm
    from app.services import llm_config_service

    # 在 StreamingResponse 构造前做全部校验/解析，错误才能以真实 HTTP 状态返回
    project, results, sections_text = load_assessment_context(
        db, user_id=current_user.id, project_id=project_id)
    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id,
        chat_source=payload.chat_source if payload else None)

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def generate():
        db.rollback()
        report = ""
        usage: dict = {}
        start = time.monotonic()
        if llm_config is None:
            yield _sse("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            return
        try:
            messages = build_assessment_messages(results, sections_text)
            async for token in astream_llm(
                messages, llm_config=llm_config, usage_sink=usage,
            ):
                report += token
                yield _sse("token", {"text": token})
            persist_assessment(db, project, content=report, model=llm_config.model)
            yield _sse("done", {
                "content": report,
                "project_id": str(project.id),
            })
        except Exception as e:
            from app.ai.llm_errors import friendly_llm_error

            yield _sse("error", {"code": "llm_error", "message": friendly_llm_error(e)})
        finally:
            from app.api.ai import _log_llm_call

            db.rollback()
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=project.id,
                action="novelty_assess",
                model=llm_config.model if llm_config else "",
                provider=llm_config.source if llm_config else "none",
                status="success" if report else "failed",
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=None if report else "no_output",
            )

    return StreamingResponse(generate(), media_type="text/event-stream")
