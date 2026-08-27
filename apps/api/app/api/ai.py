"""AI 流式 SSE 路由（异步 + 心跳 + 服务端真中断 + 断线内容保留）。"""

import asyncio
import json
import logging
import time
import traceback
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_client import astream_llm
from app.ai.llm_errors import friendly_llm_error

logger = logging.getLogger("tiangong.ai")
from app.ai.orchestrator import (
    astream_chat,
    astream_generate,
    astream_resume,
    astream_revise,
    astream_rewrite,
    build_resume_agent,
    collect_final_answer,
)
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.rate_limit import AI_LIMIT, _user_or_ip_key, limiter
from app.deps import get_current_user
from app.models import Conversation, ConversationStatus, LLMCallLog, Message, Section, User
from app.schemas.ai import (
    ChatRequest,
    ConversationCreate,
    ConversationUpdate,
    GenerateRequest,
    ResumeRequest,
    ReviseRequest,
    RewriteRequest,
)
from app.services import conversation_service, llm_config_service, section_service

router = APIRouter(tags=["ai"])

# 心跳间隔（秒）：空闲超过此值发 heartbeat 事件，防中间代理掐断
HEARTBEAT_INTERVAL = 5.0


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class _StreamMeta:
    """流式期间累积 agent 透明化元数据（tool_events + thinking），落 Message.meta 用。

    三个 SSE 端点（chat/generate/init chat）共用。工具调用按到达顺序累积成
    序列（前端据此渲染工具卡片的时间线）；thinking 文本拼接成串（流式分块
    逐 token 累加）。无任何事件时为空，build() 返回 None（不写 meta 列）。
    """

    def __init__(self) -> None:
        self.tool_events: list[dict] = []
        self._thinking_parts: list[str] = []

    def add_tool_call(self, name: str, args: dict) -> None:
        self.tool_events.append({"kind": "call", "name": name, "args": args})

    def add_tool_result(self, name: str, result: str) -> None:
        self.tool_events.append({"kind": "result", "name": name, "result": result})

    def add_thinking(self, text: str) -> None:
        if text:
            self._thinking_parts.append(text)

    def build(self) -> dict | None:
        """组装 meta dict；无内容返回 None（不污染消息）。"""
        thinking = "".join(self._thinking_parts)
        if not self.tool_events and not thinking:
            return None
        meta: dict = {}
        if self.tool_events:
            meta["tool_events"] = self.tool_events
        if thinking:
            meta["thinking"] = thinking
        return meta


def _get_section_with_history(
    db: Session, user_id, section_id: str, conversation_id: str | None = None
) -> tuple[Section, list[Message]]:
    section = section_service.get_section(db, user_id=user_id, section_id=section_id)
    query = select(Message).where(Message.section_id == section.id)
    if conversation_id:
        import uuid as _uuid
        try:
            conv_uuid = _uuid.UUID(str(conversation_id))
            query = query.where(Message.conversation_id == conv_uuid)
        except (ValueError, AttributeError):
            # 非法 conversation_id：历史为空（后续 _get_or_create_conversation 会新建）
            pass
    history = list(db.scalars(query.order_by(Message.created_at)))
    return section, history


def _get_or_create_conversation(db: Session, section: Section, conversation_id: str | None) -> Conversation:
    """获取指定会话，或创建默认会话。"""
    if conversation_id:
        import uuid as _uuid
        try:
            conv_uuid = _uuid.UUID(str(conversation_id))
            conv = db.scalar(select(Conversation).where(
                (Conversation.id == conv_uuid) & (Conversation.section_id == section.id)
            ))
            if conv:
                return conv
        except (ValueError, AttributeError):
            pass
    # 创建新会话
    conv = Conversation(section_id=section.id, title="新对话")
    db.add(conv)
    db.flush()
    return conv


def _resolve_provider(llm_config) -> str:
    """从已解析配置取 provider（用于日志 provider 字段）。无配置返回 'none'。

    复用上游已 resolve 的 config（I1：避免日志侧二次/三次 resolve 浪费 DB 查询）；
    无配置时返回 'none' 而非 'global'（I2：如实标注失败路径）。
    """
    if llm_config is None:
        return "none"
    return llm_config.source  # "user" / "global" / "env"


def _resolve_model(llm_config) -> str:
    """从已解析配置取 model（用于日志 model 字段）。无配置返回空串。

    复用上游已 resolve 的 config（I1），无配置时返回空串（I2）。
    """
    if llm_config is None:
        return ""
    return llm_config.model or ""


def _friendly_llm_error(e: Exception) -> str:
    """友好化 LLM 异常。实现已抽到 app.ai.llm_errors（供 test_llm_connection 共用）。"""
    return friendly_llm_error(e)


def _log_llm_call(
    db: Session, *,
    user_id, project_id, action: str, model: str, provider: str,
    status: str, tokens=None, duration_ms=None, error=None, context_meta=None,
) -> None:
    """写一条 LLM 调用元数据日志（设计 8.3 红线：只存元数据，不存内容）。

    tokens（断链 C3）：可选 dict {"prompt": int, "completion": int, "cached": int}，
    由各端点从流的 usage_metadata（astream_llm 的 usage_sink）捕获；
    cached（A-3）为供应商前缀缓存命中数，provider 不回传时缺省落 None。
    无值时落 None（如未开 stream_usage 或 provider 未回传 usage 的情形）。
    context_meta（spec §5.1）：可选 dict，上下文压缩 Snapshot 序列化。
    """
    try:
        from app.core.logging import get_request_id
        log = LLMCallLog(
            user_id=user_id,
            project_id=project_id,
            action=action,
            model=model,
            provider=provider,
            token_prompt=tokens.get("prompt") if tokens else None,
            token_completion=tokens.get("completion") if tokens else None,
            token_prompt_cached=tokens.get("cached") if tokens else None,
            duration_ms=duration_ms,
            status=status,
            error=(str(error)[:500] if error else None),
            context_meta=context_meta,
            request_id=get_request_id(),
        )
        db.add(log)
        db.commit()
    except Exception:
        # 日志失败不阻断主流程（已 yield 给用户的内容不丢）
        logger.warning("LLM 调用日志落库失败（不影响主流程）")
        db.rollback()


async def _yield_with_heartbeat(async_gen) -> AsyncIterator[tuple[str, str]]:
    """包装异步 token 生成器，空闲超 HEARTBEAT_INTERVAL 时插心跳事件。

    用 asyncio.wait + task 复用（而非 wait_for），避免超时时取消
    __anext__() 导致生成器被永久关闭（wait_for 的 bug 会杀掉慢速 LLM 流）。

    LLM 生成慢或长时间无 token 时，中间代理可能掐断空闲连接；
    心跳让连接保持活跃。token 与心跳交替 yield（统一 str）。

    用于 str 生成器（astream_rewrite）；agent loop 生成器 yield 元组，
    见 _yield_with_heartbeat_tuple。
    """
    ait = async_gen.__aiter__()
    nxt = asyncio.ensure_future(ait.__anext__())
    while True:
        done, _pending = await asyncio.wait({nxt}, timeout=HEARTBEAT_INTERVAL)
        if nxt in done:
            try:
                token = nxt.result()
            except StopAsyncIteration:
                break
            yield ("token", token)
            nxt = asyncio.ensure_future(ait.__anext__())
        else:
            # 超时但 task 仍在运行（不取消），发心跳保活
            yield ("heartbeat", "")


async def _yield_with_heartbeat_tuple(async_gen) -> AsyncIterator[tuple[str, object]]:
    """同 _yield_with_heartbeat，但包装 (kind, payload) 元组生成器（Task 23）。

    astream_generate / astream_chat 已改为 yield ("token"|"tool_call"|"tool_result", payload)
    元组；本包装把它们原样透传，并插入 ("heartbeat", None) 作为心跳哨兵。

    保留同样的 asyncio.wait + task 复用策略（不用 wait_for，避免超时取消
    杀掉慢速 LLM 流）。心跳路径不影响 agent loop 进行中的事件。
    """
    ait = async_gen.__aiter__()
    nxt = asyncio.ensure_future(ait.__anext__())
    while True:
        done, _pending = await asyncio.wait({nxt}, timeout=HEARTBEAT_INTERVAL)
        if nxt in done:
            try:
                item = nxt.result()
            except StopAsyncIteration:
                break
            yield item  # (kind, payload) 原样透传
            nxt = asyncio.ensure_future(ait.__anext__())
        else:
            # 超时但 task 仍在运行（不取消），发心跳保活
            yield ("heartbeat", None)


@router.post("/sections/{section_id}/chat")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def chat(
    request: Request,
    section_id: str,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section, history = _get_section_with_history(db, current_user.id, section_id, payload.conversation_id)
    conv = _get_or_create_conversation(db, section, payload.conversation_id)
    user_msg = Message(section_id=section.id, conversation_id=conv.id, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    # 阶段 0：解析生效 LLM 配置（在 StreamingResponse 构造前解析，确保
    # ForbiddenError（如全局 Key 被撤销）能被全局异常处理器转成真正的 HTTP 403，
    # 而不是在 SSE 流已发出 200 头之后才抛出 → 客户端只能看到空响应）。
    # chat_source 由前端传入（"global" / "custom-chat:{id}" / "env"），None 走 fallback。
    llm_config = llm_config_service.resolve_chat_config(db, user_id=current_user.id, chat_source=payload.chat_source)

    async def generate():
        # 防御：resolve_chat_config（外层已执行）在当前事务中做了多次 SELECT，
        # 若任一查询触发了隐性错误，事务可能已进入 aborted 状态。此处显式
        # rollback 确保 generator 内第一条 DB 操作从干净事务开始。
        db.rollback()
        full_response = ""
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        meta = {}   # 压缩 spec §5.1：astream_chat 把 snapshot 写入此 holder，供 _log_llm_call 记 context_meta
        stream_meta = _StreamMeta()  # 工具调用 + 思考过程累积，落 Message.meta（历史回灌用）
        start = time.monotonic()
        status = "success"
        err = None
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="chat",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            interrupted = False
            async for kind, data in _yield_with_heartbeat_tuple(
                astream_chat(db, section, history, payload.message,
                             llm_config=llm_config, usage_sink=usage, meta_sink=meta,
                             thread_id=str(user_msg.id))
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                elif kind == "token":
                    full_response += data
                    yield _sse_event("token", {"text": data})
                elif kind == "thinking":
                    stream_meta.add_thinking(data)
                    yield _sse_event("thinking", {"text": data})
                elif kind == "tool_call":
                    stream_meta.add_tool_call(data["name"], data["args"])
                    yield _sse_event("tool_call", {
                        "name": data["name"], "args": data["args"],
                    })
                elif kind == "tool_result":
                    stream_meta.add_tool_result(data["name"], data["result"])
                    yield _sse_event("tool_result", {
                        "name": data["name"], "result": data["result"],
                    })
                elif kind == "interrupt":
                    # HITL：agent 停在工具确认断点（如 generate_figure）。落 partial
                    # assistant 消息（meta.interrupted + 待确认动作），发 interrupt 事件
                    # 后流结束——不发 done，前端凭 interrupt 事件渲染确认卡片，
                    # 用户点「同意/拒绝」后走 resume 端点带 Command(resume=...) 续跑。
                    actions = data.get("actions", [])
                    partial_msg = Message(
                        section_id=section.id, conversation_id=conv.id, role="assistant",
                        content=full_response,
                        meta={**(stream_meta.build() or {}), "interrupted": True,
                              "pending_interrupt": actions},
                    )
                    db.add(partial_msg)
                    db.commit()
                    interrupted = True
                    yield _sse_event("interrupt", {
                        "message_id": str(partial_msg.id),
                        "thread_id": str(user_msg.id),
                        "actions": actions,
                    })
            if interrupted:
                # interrupt 分支已落库并发完事件，流到此为止（无 done）
                return
            # A-4：预算熔断发生的 turn 在消息 meta 留痕（审计与前端提示依据）
            final_meta = stream_meta.build() or {}
            if usage.get("_budget_capped"):
                final_meta["budget_capped"] = True
            ai_msg = Message(section_id=section.id, conversation_id=conv.id, role="assistant",
                             content=full_response, meta=final_meta or None)
            db.add(ai_msg)
            db.commit()

            # 草稿会话首条对话完成：同步用 LLM 总结标题，转 active，通过 done 事件回传
            # 标题生成走轻量任务模型（resolve_lite_config）：优先 admin 配的轻量模型
            #（典型 GLM-4.7-Flash），未配回退当前用户 chat 配置，与对话主体分离以省 token。
            new_title = None
            if conv.status == ConversationStatus.draft.value:
                new_title = conversation_service.summarize_conversation_title(
                    db, conv, payload.message, full_response, user_id=current_user.id
                )
                conv.title = new_title
                conv.status = ConversationStatus.active.value
                db.commit()

            yield _sse_event("done", {
                "message_id": str(ai_msg.id),
                "conversation_id": str(conv.id),
                "title": new_title,  # None 表示会话已是 active，标题未变
            })
        except asyncio.CancelledError:
            # 客户端断连（含切会话 abort）：保留已生成内容，标 incomplete 供前端区分「正常结束」与「中断的半截」。
            # interrupted 时 partial 已落库（meta.interrupted），不重复落一条 incomplete。
            if full_response and not interrupted:
                db.add(Message(section_id=section.id, conversation_id=conv.id, role="assistant",
                               content=full_response,
                               meta={**(stream_meta.build() or {}), "incomplete": True}))
                db.commit()
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            logger.exception("SSE 流式端点异常（已友好化转发前端）")
            # 异常兜底：保留已生成的部分内容（标 incomplete），不丢弃用户已看到的回复。
            # rollback 先撤销中毒事务，再新建 Message 落库；落库失败不阻塞错误上报。
            # interrupted 时 partial 已落库，不重复落。
            if full_response and not interrupted:
                try:
                    db.rollback()
                    db.add(Message(
                        section_id=section.id, conversation_id=conv.id, role="assistant",
                        content=full_response,
                        meta={**(stream_meta.build() or {}), "incomplete": True},
                    ))
                    db.commit()
                except Exception:
                    db.rollback()
            else:
                # 无内容可落时仍 rollback 确保 finally 块的 _log_llm_call 不因中毒事务二次失败
                db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": _friendly_llm_error(e)})
        finally:
            # 防御：agent loop 内任何 DB 操作失败会让事务进入 aborted 状态。
            # 此处 rollback 确保 _log_llm_call 的参数求值（current_user.id 触发
            # lazy load）和日志写入不会因事务中毒而二次失败。user_id/project_id
            # 预先取值，避免 rollback 后对象 expire 又触发 lazy load。
            try:
                _uid = current_user.id
                _pid = section.project_id
            except Exception:
                _uid = None
                _pid = None
            db.rollback()
            _log_llm_call(
                db,
                user_id=_uid,
                project_id=_pid,
                action="chat",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
                context_meta=meta.get("context_meta"),
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/messages/{message_id}/resume")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def resume_chat(
    request: Request,
    section_id: str,
    message_id: str,
    payload: ResumeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """续跑一个中断/未完成的 turn（Checkpoint 红利：断点恢复）。

    两类断点、同一入口：
    - 崩溃/断连的 turn（assistant 消息 meta.incomplete）→ input=None 从 checkpoint 续跑；
    - HITL 工具确认（meta.interrupted）→ decision=approve/reject 恢复。

    thread_id 必须是原 turn 的 user 消息 id（chat 端点的 checkpoint thread 约定），
    且与 message_id 同属一个会话——防止拿 A 会话的 thread 续跑 B 会话的消息。
    """
    import uuid as _uuid

    def _to_uuid(value, field: str):
        try:
            return _uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError(f"{field} 格式无效")

    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)

    ai_msg = db.get(Message, _to_uuid(message_id, "message_id"))
    if (ai_msg is None or ai_msg.section_id != section.id or ai_msg.role != "assistant"):
        raise NotFoundError("消息不存在")
    prev_meta: dict = dict(ai_msg.meta or {})
    if not (prev_meta.get("incomplete") or prev_meta.get("interrupted")):
        raise ConflictError("该消息没有可续跑的断点")

    user_msg = db.get(Message, _to_uuid(payload.thread_id, "thread_id"))
    if (user_msg is None or user_msg.section_id != section.id or user_msg.role != "user"
            or user_msg.conversation_id != ai_msg.conversation_id):
        raise NotFoundError("thread 对应消息不存在")

    if payload.decision is not None and payload.decision not in ("approve", "reject"):
        raise ValidationError("decision 仅支持 approve / reject")

    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id, chat_source=payload.chat_source)
    if llm_config is None:
        raise ValidationError("未配置 LLM，请先在设置中配置")

    # 构建 agent + 判可续性（在 StreamingResponse 之前，409/引导才能以真实 HTTP 状态返回）。
    # agent 复用同一实例传给 astream_resume，避免重复装配（skill 查询 + prompt 组装）。
    agent = await build_resume_agent(
        db, section, llm_config=llm_config, user_input=user_msg.content)
    state = await agent.aget_state({"configurable": {"thread_id": str(user_msg.id)}})
    if state is None or not getattr(state, "next", None):
        raise ConflictError(
            "断点已失效（服务重启后 checkpoint 丢失，或该 turn 已完成），请直接重发消息")
    pending_interrupt = any(
        getattr(t, "interrupts", None) for t in (getattr(state, "tasks", None) or []))
    if pending_interrupt and payload.decision is None:
        raise ValidationError("该断点正在等待工具确认，请选择「同意」或「拒绝」后继续")

    # 在开流前捕获 partial 基准（generate() 里 rollback 后再取会触发过期重载）
    base_content: str = ai_msg.content or ""
    conv_id_str = str(ai_msg.conversation_id)

    async def generate():
        db.rollback()
        streamed = ""
        usage = {}   # 断链 C3：astream_resume 透传 usage_metadata
        stream_meta = _StreamMeta()
        # 延续既有 partial 的工具/思考元数据，历史回灌的时间线才完整
        stream_meta.tool_events = list(prev_meta.get("tool_events") or [])
        if prev_meta.get("thinking"):
            stream_meta._thinking_parts = [prev_meta["thinking"]]
        start = time.monotonic()
        status = "success"
        err = None
        try:
            async for kind, data in _yield_with_heartbeat_tuple(
                astream_resume(db, section, llm_config=llm_config,
                               thread_id=str(user_msg.id), user_input=user_msg.content,
                               decision=payload.decision, decision_message=payload.message,
                               usage_sink=usage, agent=agent)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                elif kind == "token":
                    streamed += data
                    yield _sse_event("token", {"text": data})
                elif kind == "thinking":
                    stream_meta.add_thinking(data)
                    yield _sse_event("thinking", {"text": data})
                elif kind == "tool_call":
                    stream_meta.add_tool_call(data["name"], data["args"])
                    yield _sse_event("tool_call", {
                        "name": data["name"], "args": data["args"],
                    })
                elif kind == "tool_result":
                    stream_meta.add_tool_result(data["name"], data["result"])
                    yield _sse_event("tool_result", {
                        "name": data["name"], "result": data["result"],
                    })
                elif kind == "interrupt":
                    # 续跑中链式触发第二次工具确认：更新同一条 partial 消息后停在断点
                    actions = data.get("actions", [])
                    try:
                        db.rollback()
                        ai_msg.content = base_content + streamed
                        ai_msg.meta = {**(stream_meta.build() or {}), "interrupted": True,
                                       "pending_interrupt": actions}
                        db.commit()
                    except Exception:
                        db.rollback()
                    yield _sse_event("interrupt", {
                        "message_id": str(ai_msg.id),
                        "thread_id": str(user_msg.id),
                        "actions": actions,
                    })
                    return
            # 完成：以 checkpoint 权威重建全文（崩溃续跑时被中断节点整段重放，
            # 「DB 半截 + 续跑流」直拼会有重复前缀），失败退回拼接值；同时清除断点标记
            final_text = await collect_final_answer(agent, str(user_msg.id))
            ai_msg.content = final_text if final_text is not None else (base_content + streamed)
            ai_msg.meta = stream_meta.build()
            db.commit()

            # 首轮就被中断的草稿会话：补做标题总结（与 chat 端点对齐）
            new_title = None
            conv = db.get(Conversation, ai_msg.conversation_id)
            if conv and conv.status == ConversationStatus.draft.value:
                new_title = conversation_service.summarize_conversation_title(
                    db, conv, user_msg.content, ai_msg.content, user_id=current_user.id)
                conv.title = new_title
                conv.status = ConversationStatus.active.value
                db.commit()

            yield _sse_event("done", {
                "message_id": str(ai_msg.id),
                "conversation_id": conv_id_str,
                "title": new_title,
                # 权威全文：崩溃续跑时被中断节点整段重放，前端本地拼接的显示会有
                # 重复前缀，done 时用 DB 权威内容整体替换。
                "content": ai_msg.content,
            })
        except asyncio.CancelledError:
            # 再次中断：更新同一条 partial（保留 incomplete 标记），不新建消息
            try:
                db.rollback()
                ai_msg.content = base_content + streamed
                ai_msg.meta = {**(stream_meta.build() or {}), "incomplete": True}
                db.commit()
            except Exception:
                db.rollback()
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            logger.exception("resume SSE 端点异常（已友好化转发前端）")
            try:
                db.rollback()
                ai_msg.content = base_content + streamed
                ai_msg.meta = {**(stream_meta.build() or {}), "incomplete": True}
                db.commit()
            except Exception:
                db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": _friendly_llm_error(e)})
        finally:
            try:
                _uid = current_user.id
                _pid = section.project_id
            except Exception:
                _uid = None
                _pid = None
            db.rollback()
            _log_llm_call(
                db,
                user_id=_uid,
                project_id=_pid,
                action="chat_resume",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/generate")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def generate_draft(
    request: Request,
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    payload: GenerateRequest | None = Body(default=None),
):
    # body 可选：前端传 {chat_source} 时解析；无 body（旧调用方）默认 chat_source=None。
    chat_source = payload.chat_source if payload else None
    section, history = _get_section_with_history(db, current_user.id, section_id)

    # 阶段 0：解析生效 LLM 配置（在 StreamingResponse 构造前解析，确保
    # ForbiddenError（如全局 Key 被撤销）能被全局异常处理器转成真正的 HTTP 403，
    # 而不是在 SSE 流已发出 200 头之后才抛出 → 客户端只能看到空响应）。
    llm_config = llm_config_service.resolve_chat_config(db, user_id=current_user.id, chat_source=chat_source)

    async def generate():
        db.rollback()
        full_md = ""
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        meta = {}   # 压缩 spec §5.1：astream_generate 把 snapshot 写入此 holder
        start = time.monotonic()
        status = "success"
        err = None
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="generate",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for kind, data in _yield_with_heartbeat_tuple(
                astream_generate(db, section, history, llm_config=llm_config, usage_sink=usage, meta_sink=meta)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                elif kind == "token":
                    full_md += data
                    yield _sse_event("token", {"text": data})
                elif kind == "thinking":
                    yield _sse_event("thinking", {"text": data})
                elif kind == "tool_call":
                    yield _sse_event("tool_call", {
                        "name": data["name"], "args": data["args"],
                    })
                elif kind == "tool_result":
                    yield _sse_event("tool_result", {
                        "name": data["name"], "result": data["result"],
                    })
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
            yield _sse_event("done", {"section_id": str(section.id)})
        except asyncio.CancelledError:
            # 客户端断开：仅当 section 当前为空时落半截草稿（避免覆盖已有内容）
            if full_md and section.status == "empty":
                from app.ai.markdown_to_tiptap import markdown_to_tiptap
                section.content = markdown_to_tiptap(full_md)
                section.status = "drafting"
                db.commit()
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            logger.exception("SSE 流式端点异常（已友好化转发前端）")
            yield _sse_event("error", {"code": "llm_error", "message": _friendly_llm_error(e)})
        finally:
            # 防御：同 chat 端点，agent loop 内 DB 失败可能毒化事务，
            # rollback + 预取 id 确保 _log_llm_call 不二次失败。
            try:
                _uid = current_user.id
                _pid = section.project_id
            except Exception:
                _uid = None
                _pid = None
            db.rollback()
            _log_llm_call(
                db,
                user_id=_uid,
                project_id=_pid,
                action="generate",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
                context_meta=meta.get("context_meta"),
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/rewrite")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def rewrite(
    request: Request,
    section_id: str,
    payload: RewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)

    # 在 StreamingResponse 构造前解析，确保 ForbiddenError（如全局 Key 被撤销）能被
    # 全局异常处理器转成真正的 HTTP 403，而非 SSE 流已发 200 头后才抛（Task 4.1 同款修复）。
    llm_config = llm_config_service.resolve_chat_config(db, user_id=current_user.id, chat_source=payload.chat_source)

    async def generate():
        db.rollback()
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        start = time.monotonic()
        status = "success"
        err = None
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="rewrite",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_rewrite(section, payload.selected_text, payload.instruction,
                                llm_config=llm_config, usage_sink=usage)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    yield _sse_event("token", {"text": text})
            yield _sse_event("done", {})
        except asyncio.CancelledError:
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            logger.exception("SSE 流式端点异常（已友好化转发前端）")
            yield _sse_event("error", {"code": "llm_error", "message": _friendly_llm_error(e)})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="rewrite",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/revise")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def revise_section(
    request: Request,
    section_id: str,
    payload: ReviseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """章节针对性修订（T2 spec §3.1）：评估建议 directives → 流式修订稿。

    与 generate 的本质差异：产出是**候选稿**——不写 section.content、不建 Message、
    不建 conversation，全文经 done.content 返回，前端走 /diff + apply-diff 人工审核
    应用（spec D8）。astream_revise 内部 checkpointer=None（spec §3.1.3）。
    """
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)

    # 空内容 409：判据 content 抽纯文本非全空白（不看 status——drafting 也可能断连半截空）
    from app.services.novelty_service import _extract_text
    if not section.content or not _extract_text(section.content).strip():
        raise ConflictError("章节尚无内容，请先撰写或生成草稿")

    # 开流前解析，确保 ForbiddenError 转成真实 HTTP 403（chat/generate 同款约定）
    llm_config = llm_config_service.resolve_chat_config(db, user_id=current_user.id, chat_source=payload.chat_source)

    async def generate():
        db.rollback()
        full_md = ""
        usage = {}
        start = time.monotonic()
        status = "success"
        err = None
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="revise",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for kind, data in _yield_with_heartbeat_tuple(
                astream_revise(db, section, payload.directives,
                                llm_config=llm_config, usage_sink=usage)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                elif kind == "token":
                    full_md += data
                    yield _sse_event("token", {"text": data})
                elif kind == "thinking":
                    yield _sse_event("thinking", {"text": data})
                elif kind == "tool_call":
                    yield _sse_event("tool_call", {
                        "name": data["name"], "args": data["args"],
                    })
                elif kind == "tool_result":
                    yield _sse_event("tool_result", {
                        "name": data["name"], "result": data["result"],
                    })
            # 不落库（spec §3.1.2-4）：done 带权威全文，候选稿交前端走 diff 审核
            yield _sse_event("done", {"content": full_md, "section_id": str(section.id)})
        except asyncio.CancelledError:
            # 客户端断开：丢弃缓冲（不落库）——建议源在报告页持久存在，可重新发起
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            logger.exception("SSE 流式端点异常（已友好化转发前端）")
            yield _sse_event("error", {"code": "llm_error", "message": _friendly_llm_error(e)})
        finally:
            try:
                _uid = current_user.id
                _pid = section.project_id
            except Exception:
                _uid = None
                _pid = None
            db.rollback()
            _log_llm_call(
                db,
                user_id=_uid,
                project_id=_pid,
                action="revise",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
                context_meta={"origin": payload.origin},
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sections/{section_id}/messages")
def list_messages(
    section_id: str,
    conversation_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出某会话的历史消息。

    conversation_id 为必填：缺省时返回 422，避免前端漏传时把 section 下
    所有会话的消息混在一起（串历史 bug 的根因）。
    """
    if not conversation_id:
        raise ValidationError("conversation_id 为必填参数")
    import uuid as _uuid
    try:
        conv_uuid = _uuid.UUID(str(conversation_id))
    except (ValueError, AttributeError):
        raise ValidationError("conversation_id 格式无效")
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    query = (
        select(Message)
        .where(Message.section_id == section.id)
        .where(Message.conversation_id == conv_uuid)
    )
    messages = list(db.scalars(query.order_by(Message.created_at)))
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "meta": m.meta,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


# ── 会话管理 ──

@router.get("/sections/{section_id}/conversations")
def list_conversations(
    section_id: str,
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出 section 下的所有会话（按最后更新倒序）。

    status 可选过滤：draft / active / None(全部，默认)。
    """
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    query = (
        select(Conversation)
        .where(Conversation.section_id == section.id)
    )
    if status:
        query = query.where(Conversation.status == status)
    convs = list(db.scalars(query.order_by(Conversation.updated_at.desc())))
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "status": c.status,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in convs
    ]


@router.post("/sections/{section_id}/conversations", status_code=201)
def create_conversation(
    section_id: str,
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新建会话（默认 status=draft，占位标题「新会话」，首条对话后转 active）。"""
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    conv = Conversation(
        section_id=section.id,
        title=payload.title or "新会话",
        status=ConversationStatus.draft.value,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {
        "id": str(conv.id),
        "title": conv.title,
        "status": conv.status,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }


@router.patch("/sections/{section_id}/conversations/{conversation_id}")
def update_conversation(
    section_id: str,
    conversation_id: str,
    payload: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重命名会话。"""
    import uuid as _uuid
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    conv = db.scalar(select(Conversation).where(
        (Conversation.id == _uuid.UUID(conversation_id)) & (Conversation.section_id == section.id)
    ))
    if conv is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("会话不存在")
    conv.title = payload.title
    db.commit()
    db.refresh(conv)  # expire_on_commit=False：需显式刷新拿 onupdate 的 updated_at
    return {
        "id": str(conv.id),
        "title": conv.title,
        "status": conv.status,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }


@router.delete("/sections/{section_id}/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    section_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除会话（级联删除消息）。"""
    import uuid as _uuid
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    conv = db.scalar(select(Conversation).where(
        (Conversation.id == _uuid.UUID(conversation_id)) & (Conversation.section_id == section.id)
    ))
    if conv:
        db.delete(conv)
        db.commit()
    return None


class CaptionRequest(BaseModel):
    descriptions: list[str] = []  # 用户手写文字描述（降级/补充用），默认空
    attachment_ids: list[str] = []  # 要"看图"的附件 id，vision 模型时走多模态
    chat_source: str | None = None


@router.post("/sections/{section_id}/caption-figures")
async def caption_figures(
    section_id: str,
    payload: CaptionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """图注润色：基于附图图片内容（多模态 vision）或文字描述生成规范图注（设计 9.5）。

    vision 模型 + attachment_ids → 真正"看图说话"；否则降级纯文字润色（呼应设计 9.5
    顾虑③「并非所有接口支持 vision」）。直接用 astream_llm 流式生成（不走 heartbeat
    包装，简化文本生成）。与其它 LLM 端点一致：成功/失败均写 LLMCallLog（断链 C3）。
    """
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    # 仅附图章节可用
    if section.key != "drawings":
        raise ValidationError("图注润色仅限附图章节")
    if not payload.descriptions and not payload.attachment_ids:
        raise ValidationError("至少提供 descriptions 或 attachment_ids 之一")

    import uuid

    from app.ai.vision import build_caption_messages, is_vision_model, resolve_vision_markers
    from app.core.storage import get_storage
    from app.models import Attachment

    # chat_source 由前端传入；在 StreamingResponse 构造前解析，与其它端点保持一致
    llm_config = llm_config_service.resolve_chat_config(db, user_id=current_user.id, chat_source=payload.chat_source)

    # 取附件图片字节：按 attachment_id 查，归属校验防越权（非法/跨项目一律跳过不报错）
    images: list[tuple[bytes, str]] = []
    for aid in payload.attachment_ids:
        try:
            att_id = uuid.UUID(aid)
        except (ValueError, TypeError):
            continue
        att = db.get(Attachment, att_id)
        if att is None or not att.storage_path:
            continue
        if str(att.project_id) != str(section.project_id):
            continue
        data = get_storage().get("personal", att.storage_path)
        if data:
            images.append((data, att.mime_type or "image/png"))

    # vision 模型 + 拿到字节 → 多模态看图；否则降级纯文字。
    # 名单可由 admin 配置（vision_model_markers：extra 合并 / enabled 开关），无配置时内置默认。
    use_vision = bool(images) and is_vision_model(
        _resolve_model(llm_config) if llm_config else None,
        markers=resolve_vision_markers(db),
    )

    # 非 vision 模型 + 无有效文字描述：直接报可行动错误，不调 LLM。
    # 否则会拿「（无文字描述）」喂给模型，模型只能回复「请提供描述」——
    # 这段话被当成图注展示/插入文档（dogfood 实际踩到）。
    _descs = [d.strip() for d in payload.descriptions if d and d.strip()]
    if not use_vision and not _descs:
        model_name = _resolve_model(llm_config) if llm_config else None
        logger.warning(f"图注润色降级拦截：模型 {model_name} 非 vision 且无文字描述")
        raise ValidationError(
            "当前 chat 模型不支持看图（vision），且未提供文字描述，无法生成图注。"
            "请填写各图的文字描述（部件/连接关系等），或在设置中切换支持 vision 的模型"
            "（如 glm-4v 系列）。"
        )

    messages = build_caption_messages(_descs, images, use_vision=use_vision)

    async def generate():
        db.rollback()
        usage = {}  # 断链 C3：astream_llm 把最后一块 usage_metadata 写入此 holder
        start = time.monotonic()
        status = "success"
        err = None
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            _log_llm_call(
                db, user_id=current_user.id, project_id=section.project_id, action="caption",
                model=_resolve_model(llm_config), provider=_resolve_provider(llm_config),
                status="failed", duration_ms=int((time.monotonic() - start) * 1000),
                error="no_llm_config",
            )
            return
        try:
            async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage):
                yield _sse_event("token", {"text": token})
            yield _sse_event("done", {})
        except asyncio.CancelledError:
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            logger.exception("SSE 流式端点异常（已友好化转发前端）")
            yield _sse_event("error", {"code": "llm_error", "message": _friendly_llm_error(e)})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="caption",
                model=_resolve_model(llm_config),
                provider=_resolve_provider(llm_config),
                status=status,
                tokens=usage or None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )

    return StreamingResponse(generate(), media_type="text/event-stream")
