from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UsersRead(BaseModel):
    users: list[UserRead]
    # The user this request acts for: the one its `X-Raton-User` header or `raton_user` cookie
    # names, else the oldest one.
    current_user_id: int


class UserWrite(BaseModel):
    name: str
