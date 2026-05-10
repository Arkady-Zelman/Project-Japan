"""Pydantic schemas for the AI Analyst — chat request/response + tool I/O."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ToolName = Literal[
    "query_data",
    "describe_schema",
    "create_chart",
    "run_correlation",
    "fit_quick_model",
    "value_what_if",
    "get_user_assets",
]

StreamEventType = Literal[
    "session", "token", "tool_call", "tool_result", "artifact",
    "message", "done", "error",
]


class ChatRequest(BaseModel):
    """One user turn POSTed to `/chat`. session_id=None → create new session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    message: str = Field(min_length=1, max_length=8_000)


class ToolCall(BaseModel):
    """One tool invocation extracted from an OpenAI assistant message."""

    model_config = ConfigDict(extra="forbid")

    id: str                # OpenAI's tool_call_id
    name: ToolName
    arguments: dict


class ToolResult(BaseModel):
    """Result of executing a single tool call. `error` is set iff success=False."""

    model_config = ConfigDict(extra="forbid")

    id: str                # matches ToolCall.id
    name: ToolName
    success: bool
    output: dict | list | str | int | float | None = None
    error: str | None = None
    artifact_id: UUID | None = None    # populated by create_chart


class StreamEvent(BaseModel):
    """One SSE event from the agent loop."""

    model_config = ConfigDict(extra="forbid")

    type: StreamEventType
    payload: dict
