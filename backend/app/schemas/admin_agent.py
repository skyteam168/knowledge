from typing import Literal

from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AgentChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[AgentMessage] = Field(default_factory=list, max_length=40)


class AgentExecuteIn(BaseModel):
    # Required for high-risk plans: the admin ticked "I understand the risk".
    acknowledge_risk: bool = False
