"""OpenAI function-calling loop with SSE streaming.

One async generator yielding `StreamEvent` items per BUILD_SPEC §9.

Loop:
  1. Compute remaining session-token budget; reject early if exceeded.
  2. Stream from OpenAI with `tools=...`, capturing tokens + tool_calls.
  3. When the model finishes (`finish_reason='stop'`): emit done, persist
     the assistant message, exit.
  4. When the model emits tool_calls: persist the assistant message with
     the tool_calls jsonb, execute each tool (in parallel via threadpool),
     emit `tool_result` events, persist tool messages, loop.

Per spec §9.4 every tool call is wrapped in `compute_run("agent_tool_call")`
inside the tool itself; no double-wrapping here.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
from collections.abc import AsyncIterator
from uuid import UUID

import openai

from common.db import connect

from .models import StreamEvent
from .prompts import build_system_prompt
from .safety import SESSION_TOKEN_LIMIT, get_session_token_total
from .tools import TOOLS, ToolContext, openai_tool_schemas

logger = logging.getLogger("agent.loop")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
MAX_LOOP_ITERATIONS = 8     # Hard cap on tool-call rounds per turn.

_threadpool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _persist_message(
    session_id: UUID, role: str, content: str | None,
    tool_calls: list[dict] | None = None,
    tool_results: list[dict] | None = None,
    tokens_in: int | None = None, tokens_out: int | None = None,
) -> None:
    """Insert a chat_messages row via the service-role connection."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into chat_messages
              (session_id, role, content, tool_calls, tool_results,
               tokens_in, tokens_out)
            values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                str(session_id), role, content or "",
                json.dumps(tool_calls or []),
                json.dumps(tool_results or []),
                tokens_in, tokens_out,
            ),
        )
        conn.commit()


def _load_session_messages(session_id: UUID) -> list[dict]:
    """Reconstruct the OpenAI messages list from chat_messages."""
    out: list[dict] = []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select role, content, tool_calls::text, tool_results::text
            from chat_messages where session_id = %s
            order by created_at, id
            """,
            (str(session_id),),
        )
        for role, content, tool_calls_json, tool_results_json in cur.fetchall():
            tool_calls = json.loads(tool_calls_json) if tool_calls_json else []
            tool_results = json.loads(tool_results_json) if tool_results_json else []
            if role == "tool":
                # Each tool_results entry becomes its own tool message in OpenAI format.
                for tr in tool_results:
                    out.append({
                        "role": "tool",
                        "tool_call_id": tr.get("id"),
                        "content": json.dumps(tr.get("output", tr)),
                    })
            elif role == "assistant" and tool_calls:
                msg: dict = {"role": "assistant", "content": content or None}
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {
                            "name": tc.get("name"),
                            "arguments": json.dumps(tc.get("arguments", {})),
                        },
                    }
                    for tc in tool_calls
                ]
                out.append(msg)
            else:
                out.append({"role": role, "content": content or ""})
    return out


async def run_agent_loop(
    user_id: UUID, session_id: UUID, user_message: str,
) -> AsyncIterator[StreamEvent]:
    """Run the OpenAI function-calling loop. Yields SSE events as it goes."""
    # 1) Token-budget gate.
    with connect() as conn, conn.cursor() as cur:
        already = get_session_token_total(cur, session_id)
    if already >= SESSION_TOKEN_LIMIT:
        yield StreamEvent(
            type="error",
            payload={"message": (
                f"Session token budget exhausted ({already}/{SESSION_TOKEN_LIMIT}). "
                f"Start a new chat to continue."
            )},
        )
        yield StreamEvent(type="done", payload={})
        return

    # 2) Persist the user message + reconstruct history.
    _persist_message(session_id, "user", user_message)

    messages: list[dict] = [{"role": "system", "content": build_system_prompt()}]
    messages.extend(_load_session_messages(session_id))

    client = openai.AsyncOpenAI()
    ctx = ToolContext(user_id=user_id, session_id=session_id)
    tool_schemas = openai_tool_schemas()

    for iteration in range(MAX_LOOP_ITERATIONS):
        try:
            stream = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                tools=tool_schemas,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as e:
            logger.exception("OpenAI request failed")
            yield StreamEvent(type="error", payload={"message": f"OpenAI error: {e}"})
            yield StreamEvent(type="done", payload={})
            return

        assistant_text_chunks: list[str] = []
        tool_calls_acc: dict[int, dict] = {}     # by chunk.index
        tokens_in = tokens_out = 0
        finish_reason: str | None = None

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                tokens_in = int(usage.prompt_tokens or 0)
                tokens_out = int(usage.completion_tokens or 0)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            finish_reason = choice.finish_reason or finish_reason
            if delta is None:
                continue
            if delta.content:
                assistant_text_chunks.append(delta.content)
                yield StreamEvent(type="token", payload={"text": delta.content})
            if delta.tool_calls:
                for tcd in delta.tool_calls:
                    idx = tcd.index
                    acc = tool_calls_acc.setdefault(
                        idx, {"id": "", "type": "function",
                              "function": {"name": "", "arguments": ""}},
                    )
                    if tcd.id:
                        acc["id"] = tcd.id
                    if tcd.function:
                        if tcd.function.name:
                            acc["function"]["name"] = tcd.function.name
                        if tcd.function.arguments:
                            acc["function"]["arguments"] += tcd.function.arguments

        # Assistant text done.
        assistant_text = "".join(assistant_text_chunks)
        ordered_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
        # Append the assistant message to the OpenAI history (raw form).
        if ordered_calls:
            messages.append({
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": ordered_calls,
            })
        else:
            messages.append({"role": "assistant", "content": assistant_text})

        # Persist as one chat_messages row (assistant), with tool_calls jsonb.
        persisted_calls = [
            {
                "id": tc["id"], "name": tc["function"]["name"],
                "arguments": _safe_json_loads(tc["function"]["arguments"]),
            }
            for tc in ordered_calls
        ]
        _persist_message(
            session_id, "assistant", assistant_text or None,
            tool_calls=persisted_calls,
            tokens_in=tokens_in or None, tokens_out=tokens_out or None,
        )
        if assistant_text:
            yield StreamEvent(
                type="message", payload={"role": "assistant", "content": assistant_text},
            )

        # No tool calls → done.
        if finish_reason == "stop" or not ordered_calls:
            yield StreamEvent(type="done", payload={})
            return

        # Execute each tool call (parallel via threadpool).
        loop = asyncio.get_running_loop()
        tool_results = []
        async_tasks = []
        for tc in ordered_calls:
            name = tc["function"]["name"]
            arguments = _safe_json_loads(tc["function"]["arguments"])
            yield StreamEvent(
                type="tool_call",
                payload={"id": tc["id"], "name": name, "arguments": arguments},
            )
            tool_fn = TOOLS.get(name)
            if tool_fn is None:
                tool_results.append((tc, {"success": False, "error": f"unknown tool: {name}"}))
                continue
            fut = loop.run_in_executor(_threadpool, tool_fn, arguments, ctx)
            async_tasks.append((tc, fut))

        # Await all in flight.
        for tc, fut in async_tasks:
            result = await fut
            tool_results.append((tc, result))

        # Emit tool_result events + append to message history + persist.
        persisted_tool_results = []
        for tc, result in tool_results:
            yield StreamEvent(
                type="tool_result",
                payload={
                    "id": tc["id"], "name": tc["function"]["name"],
                    "success": bool(result.get("success", False)),
                    "output": result,
                },
            )
            if result.get("artifact_id"):
                yield StreamEvent(
                    type="artifact",
                    payload={"artifact_id": result["artifact_id"], "type": "chart"},
                )
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })
            persisted_tool_results.append({
                "id": tc["id"],
                "name": tc["function"]["name"],
                "output": result,
            })
        _persist_message(
            session_id, "tool", None, tool_results=persisted_tool_results,
        )

    # Hit the loop cap.
    yield StreamEvent(
        type="error",
        payload={"message": f"agent loop exceeded {MAX_LOOP_ITERATIONS} tool-call rounds"},
    )
    yield StreamEvent(type="done", payload={})


def _safe_json_loads(s: str) -> dict:
    try:
        v = json.loads(s) if s else {}
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
