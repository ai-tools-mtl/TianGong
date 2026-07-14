from datetime import datetime

from pydantic import BaseModel


class RubricOut(BaseModel):
    id: str
    scope: str
    name: str
    criteria: list[dict]
    is_customized: bool

    model_config = {"from_attributes": True}


class RubricUpdate(BaseModel):
    name: str | None = None
    criteria: list[dict] | None = None
