"""Shared bearer-token guard for public Modal HTTP endpoints."""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials


def require_modal_api_token(credentials: HTTPAuthorizationCredentials | None) -> None:
    """Fail closed unless Authorization: Bearer <MODAL_API_TOKEN> matches."""
    expected = os.environ.get("MODAL_API_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MODAL_API_TOKEN is not configured",
        )
    if credentials is None or not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid Modal API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
