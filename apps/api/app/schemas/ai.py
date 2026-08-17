from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str
    chat_source: str | None = None  # "global" / "custom-chat:{id}" / "env"；None 走 fallback
    conversation_id: str | None = None


class GenerateRequest(BaseModel):
    chat_source: str | None = None


class ResumeRequest(BaseModel):
    """续跑一个中断/未完成的 turn。

    thread_id：原 turn 的 user 消息 id（checkpoint thread 约定，见 ai.py chat 端点）。
    decision：HITL 中断恢复时的决策（"approve" / "reject"）；None = 崩溃续跑（input=None）。
    message：reject 时给 agent 的说明（可选）。
    """
    thread_id: str
    decision: str | None = None
    message: str | None = None
    chat_source: str | None = None


class RewriteRequest(BaseModel):
    selected_text: str
    instruction: str = "重写这段内容，使其更清晰规范"
    chat_source: str | None = None


_REVISE_ORIGINS = {"review", "novelty", "terms", "manual"}


class ReviseRequest(BaseModel):
    """章节针对性修订（T2 spec §3.1.1）：评估建议 → directives → 流式修订稿。

    directives 由前端从审查报告/术语检查/新颖性建议组装（用户在确认卡片勾选）；
    origin 仅用于 LLMCallLog 记账标注来源，不影响行为。
    """
    directives: list[str] = Field(min_length=1, max_length=10)
    origin: str = "manual"
    chat_source: str | None = None

    @field_validator("directives")
    @classmethod
    def _each_directive(cls, v: list[str]) -> list[str]:
        stripped = [d.strip() for d in v]
        for d in stripped:
            if not d or len(d) > 500:
                raise ValueError("每条修订指令须为 1..500 字（去空白后）")
        return stripped

    @field_validator("origin")
    @classmethod
    def _origin_ok(cls, v: str) -> str:
        if v not in _REVISE_ORIGINS:
            raise ValueError("origin 非法（review/novelty/terms/manual）")
        return v


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str
