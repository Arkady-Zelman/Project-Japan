from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from common.http_auth import require_modal_api_token


def test_require_modal_api_token_accepts_matching_bearer(monkeypatch) -> None:
    monkeypatch.setenv("MODAL_API_TOKEN", "secret-token")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-token")

    require_modal_api_token(credentials)


def test_require_modal_api_token_rejects_missing_or_wrong_token(monkeypatch) -> None:
    monkeypatch.setenv("MODAL_API_TOKEN", "secret-token")

    with pytest.raises(HTTPException) as missing:
        require_modal_api_token(None)
    assert missing.value.status_code == 401

    wrong = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
    with pytest.raises(HTTPException) as rejected:
        require_modal_api_token(wrong)
    assert rejected.value.status_code == 401


def test_require_modal_api_token_fails_closed_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("MODAL_API_TOKEN", raising=False)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-token")

    with pytest.raises(HTTPException) as exc:
        require_modal_api_token(credentials)
    assert exc.value.status_code == 500
