from pydantic import BaseModel


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


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str
