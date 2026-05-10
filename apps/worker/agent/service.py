"""FastAPI ASGI app for the AI Analyst.

Endpoints:
  GET  /health         — liveness probe
  POST /chat           — SSE-streamed turn. Body: {session_id?, message}.
                         Header: X-User-Id (the dev-user shim relayed from
                         Vercel; in M9.5 this becomes a Supabase JWT).

Per BUILD_SPEC §11 this is wrapped in `@modal.asgi_app(label="agent")` in
`modal_app.py`. SSE comes from `sse-starlette`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-untyped]

from common.db import connect

from .loop import run_agent_loop
from .models import ChatRequest, StreamEvent

logger = logging.getLogger("agent.service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_app() -> FastAPI:
    app = FastAPI(title="JEPX Analyst", version="0.1")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "service": "agent"}

    @app.post("/chat")
    async def chat(req: ChatRequest, x_user_id: str = Header(...)) -> EventSourceResponse:
        try:
            user_id = UUID(x_user_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid X-User-Id: {e}") from e

        session_id = _resolve_session(req.session_id, user_id)

        async def event_stream() -> AsyncIterator[dict]:
            # First event: announce the session_id so the client can
            # subscribe to Realtime channels.
            yield _sse_event(StreamEvent(
                type="session", payload={"session_id": str(session_id)},
            ))
            try:
                async for ev in run_agent_loop(user_id, session_id, req.message):
                    yield _sse_event(ev)
            except Exception as e:
                logger.exception("agent loop crashed")
                yield _sse_event(StreamEvent(
                    type="error", payload={"message": f"agent crashed: {e}"},
                ))
                yield _sse_event(StreamEvent(type="done", payload={}))

        return EventSourceResponse(event_stream())

    return app


def _resolve_session(session_id_str: str | None, user_id: UUID) -> UUID:
    """Return an existing session_id (validated against the user) or create one."""
    if session_id_str:
        try:
            sid = UUID(session_id_str)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid session_id: {e}") from e
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select user_id from chat_sessions where id = %s",
                (str(sid),),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="session not found")
        if str(row[0]) != str(user_id):
            raise HTTPException(status_code=403, detail="session belongs to another user")
        return sid

    # Create a new session.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into chat_sessions (user_id, title) values (%s, %s) returning id::text",
            (str(user_id), "New chat"),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="failed to create session")
        new_id = UUID(row[0])
        conn.commit()
    return new_id


def _sse_event(ev: StreamEvent) -> dict:
    """Format a StreamEvent as an `sse-starlette` event dict."""
    return {"event": ev.type, "data": json.dumps(ev.payload)}
