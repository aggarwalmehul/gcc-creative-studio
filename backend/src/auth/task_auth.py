"""Verifies that an incoming request is a genuine Cloud Tasks OIDC-signed
call, before it is allowed to hit the thumbnail worker route.
"""

import asyncio
import logging
from os import getenv

from fastapi import Header, HTTPException, status
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token

from src.config.config_service import config_service

logger = logging.getLogger(__name__)

# FEATURE_PORT_CLOUD_TASKS_THUMBNAILS_V1: match task_queue.py -- verify against the SAME
# SIGNING_SA_EMAIL identity that was used to mint the token, read the
# same way (os.getenv, not via config_service).
_SIGNING_SA_EMAIL = getenv("SIGNING_SA_EMAIL", "")


async def verify_cloud_tasks_oidc(
    authorization: str = Header(default=""),
) -> dict:
    """FastAPI dependency: validates the Bearer token Cloud Tasks attaches
    to its HTTP push requests, rejecting anything else.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    token = authorization.split(" ", 1)[1]
    try:
        claims = await asyncio.to_thread(
            id_token.verify_oauth2_token,
            token,
            google_auth_requests.Request(),
            audience=config_service.TASKS_WORKER_URL,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[verify_cloud_tasks_oidc] Invalid OIDC token: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid OIDC token: {e}",
        ) from e

    expected_email = _SIGNING_SA_EMAIL
    if expected_email and claims.get("email") != expected_email:
        logger.error(
            "[verify_cloud_tasks_oidc] Unexpected invoker SA: %s",
            claims.get("email"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unexpected task invoker service account.",
        )
    return claims
