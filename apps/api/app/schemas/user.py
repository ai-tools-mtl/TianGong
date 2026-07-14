from pydantic import BaseModel, EmailStr


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    status: str

    model_config = {"from_attributes": True}
