from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class GenerateRequest(BaseModel):
    pass


class RewriteRequest(BaseModel):
    selected_text: str
    instruction: str = "重写这段内容，使其更清晰规范"
