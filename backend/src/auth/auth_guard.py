# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Authentication guards and user retrieval."""


import asyncio
import logging

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from firebase_admin import auth

# --- Google Auth for Identity Platform ---
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token

from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService
import os
from src.common.token_logger import current_user_email
from src.workspaces.workspace_service import WorkspaceService
from src.workspaces.dto.create_workspace_dto import CreateWorkspaceDto
from src.common.request_context import is_agent_request

# Initialize the scheme without auto_error so we can handle fallback internal auth
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


logger = logging.getLogger(__name__)


_AGENT_TOKENS_ENABLED = os.getenv("ALLOW_AGENT_ACCESS_TOKENS", "").lower() == "true"


async def _verify_firebase_token(token: str) -> dict | None:
    """AUTH_MERGE_SYNC_V1: try Firebase first (frontend uses signInWithPopup).

    Returns None to fall back to Google OIDC. Expired/invalid Firebase tokens
    are re-raised (AUTH_FALLBACK_MASKING_FIX_V1) so callers get a clean 401.
    """
    try:
        logger.info("Verifying token using Firebase Admin SDK...")
        return await asyncio.to_thread(auth.verify_id_token, token)
    except (auth.ExpiredIdTokenError, auth.InvalidIdTokenError):
        raise
    except Exception as fb_err:  # noqa: BLE001
        logger.info("Firebase verify failed (%s); trying Google OIDC...", fb_err)
        return None

async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    user_service: UserService = Depends(UserService),
    workspace_service: WorkspaceService = Depends(WorkspaceService),
) -> UserModel:
    """Dependency that handles the entire authentication and user
    provisioning flow. Supports standard token or internal agent key auth.
    """
    try:
        is_agent_request.set(False)
        user_auth_header = request.headers.get("X-User-Authorization")
        if user_auth_header:
            is_agent_request.set(True)
            token = (
                user_auth_header.replace("Bearer ", "")
                .replace("bearer ", "")
                .strip()
            )

        # 2. Fall back to Token verification
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token.",
            )

        decoded_token = {}
        # AUTH_MERGE_SYNC_V1: upstream agent access-token path, off unless
        # ALLOW_AGENT_ACCESS_TOKENS=true (tokeninfo has no audience check).
        if token.startswith("ya29.") and _AGENT_TOKENS_ENABLED:
            # --- Verify Google OAuth Access Token (Agent Engine) ---
            logger.info("Verifying Google OAuth Access Token...")
            import requests

            try:
                response = await asyncio.to_thread(
                    requests.get,
                    f"https://oauth2.googleapis.com/tokeninfo?access_token={token}",
                    timeout=10,
                )
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Invalid Google access token: {response.text}",
                    )
                decoded_token = response.json()
            except requests.RequestException as req_err:
                logger.error(
                    "Failed to verify Google access token: %s", req_err
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to contact Google authentication server.",
                )

            if not decoded_token or "email" not in decoded_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Google access token.",
                )

            if "name" not in decoded_token and "email" in decoded_token:
                email_prefix = decoded_token["email"].split("@")[0]
                decoded_token["name"] = (
                    email_prefix if len(email_prefix) >= 2 else "User"
                )
        elif (decoded_token := await _verify_firebase_token(token)) is not None:
            pass
        else:
            # --- Google Identity Platform (OIDC) fallback ---
            google_token_audience = config_service.GOOGLE_TOKEN_AUDIENCE
            decoded_token = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                token,
                google_auth_requests.Request(),
                audience=google_token_audience,
            )

        email = decoded_token.get("email")
        try:
            current_user_email.set(email or "unknown")
        except Exception:
            pass
        name = decoded_token.get("name")
        picture = decoded_token.get("picture", "")
        token_info_hd = decoded_token.get("hd")

        # Restrict by particular organizations if it's a closed environment
        if not email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden: User identity could not be confirmed from "
                    "token."
                ),
            )

        # AUTH_MERGE_SYNC_V1: upstream email allow-list + our email-domain
        # fallback (Firebase tokens lack 'hd').
        effective_hd = token_info_hd
        if not effective_hd and email:
            effective_hd = email.split("@")[-1].lower()

        is_allowed = False
        if config_service.ALLOWED_EMAILS and email in config_service.ALLOWED_EMAILS:
            is_allowed = True
        if (
            not is_allowed
            and config_service.ALLOWED_ORGS
            and effective_hd in config_service.ALLOWED_ORGS
        ):
            is_allowed = True
        if (
            config_service.ALLOWED_EMAILS or config_service.ALLOWED_ORGS
        ) and not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is not authorized to access this application.",
            )

        # Just-In-Time (JIT) User Provisioning:
        # Create a user profile in our database on their first API call.
        user_doc = await user_service.create_user_if_not_exists(
            email=email,
            name=name,
            picture=picture,
        )

        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not create or retrieve user profile.",
            )

        if not user_doc.picture and picture:
            logger.info("Updating picture for user: %s", email)
            user_doc.picture = picture
            if user_doc.id:
                await user_service.user_repo.update(
                    user_doc.id, {"picture": picture}
                )

        # Auto-provision a default workspace on first login so every
        # colleague can start immediately (no "select a workspace" error).
        try:
            existing_ws = await workspace_service.list_workspaces_for_user(
                user_doc
            )
            if not existing_ws:
                ws_name = f"{(user_doc.name or 'My').strip()} Workspace"
                if len(ws_name) < 3:
                    ws_name = "My Workspace"
                await workspace_service.create_workspace(
                    user_doc,
                    CreateWorkspaceDto(name=ws_name),
                )
                logger.info(
                    "Auto-created default workspace for user: %s", email
                )
        except Exception as ws_exc:  # noqa: BLE001
            logger.warning(
                "Could not auto-create workspace for %s: %s", email, ws_exc
            )

        return user_doc

    except auth.ExpiredIdTokenError as exc:
        logger.error(
            "[get_current_user - auth.ExpiredIdTokenError] for %s",
            email or "Unknown email",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
        ) from exc
    except auth.InvalidIdTokenError as e:
        logger.error(
            "[get_current_user - auth.InvalidIdTokenError] for %s: %s",
            email or "Unknown email",
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {e}",
        ) from e
    except HTTPException as e:
        logger.error("[get_current_user - Exception]: %s", e)
        raise e
    except Exception as e:
        logger.error("[get_current_user - Exception]: %s", e)
        raise HTTPException(
            status_code=getattr(
                e,
                "status_code",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            detail=f"An unexpected error occurred during authentication: {e}",
        ) from e


class RoleChecker:
    """Dependency that checks if the authenticated user has the required roles.
    It depends on `get_current_user` to ensure the user is authenticated first.
    """

    def __init__(self, allowed_roles: list[UserRoleEnum]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: UserModel = Depends(get_current_user)):
        """Checks the user's roles against the allowed roles."""
        is_authorized = any(role in self.allowed_roles for role in user.roles)

        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You do not have sufficient permissions to perform this "
                    "action."
                ),
            )
