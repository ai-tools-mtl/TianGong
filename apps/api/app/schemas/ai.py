from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    source: str | None = None  # "global" / "byok:{id}" / "env"；None 走 fallback
    conversation_id: str | None = None


class GenerateRequest(BaseModel):
    source: str | None = None


class RewriteRequest(BaseModel):
    selected_text: str
    instruction: str = "重写这段内容，使其更清晰规范"
    source: str | None = None


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str
