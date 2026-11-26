"""AUTH_UNBOUND_EMAIL_FIX_V1: a token failure must give 401, not UnboundLocalError (500)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from firebase_admin import auth

from src.auth import auth_guard


def _call(exc):
    request = MagicMock()
    request.headers = {}
    with patch.object(auth_guard, "_verify_firebase_token", AsyncMock(side_effect=exc)):
        return asyncio.run(
            auth_guard.get_current_user(
                request=request,
                token="expired-or-invalid-token",
                user_service=MagicMock(),
                workspace_service=MagicMock(),
            )
        )


def test_expired_token_returns_401():
    with pytest.raises(HTTPException) as e:
        _call(auth.ExpiredIdTokenError("expired", None))
    assert e.value.status_code == 401
    assert "expired" in e.value.detail.lower()


def test_invalid_token_returns_401():
    with pytest.raises(HTTPException) as e:
        _call(auth.InvalidIdTokenError("bad token"))
    assert e.value.status_code == 401
