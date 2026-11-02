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

"""OWNERSHIP_CHECK_V1: ensures a user-referenced media_item or source_asset
actually belongs to the caller before it's used as an input to a generation
job. Prevents cross-workspace/cross-user ID-guessing: previously
`media_repo.get_by_id(ref.id)` / `source_asset_repo.get_by_id(...)` would
return ANY row for ANY workspace/user as long as the numeric ID existed.

Two different access models are used, matching the codebase's existing,
pre-existing conventions exactly (not introduced by this patch):

- media_item -> WORKSPACE-shared, matching gallery_service.get_media_by_id
  (any member of the item's workspace, via WorkspaceAuth.authorize).
- source_asset -> OWNER-private, matching source_asset_service.get_asset_by_id
  and the /source_assets/search endpoint (admin, the uploader, or SYSTEM
  scope -- workspace membership alone is NOT sufficient, same as every other
  source-asset read path in the app).

Both helpers return None on any mismatch, exactly matching the "not found"
return value every existing call site already handles -- no downstream
behavior changes except that disallowed references now also resolve to
"not found" instead of silently succeeding.
"""

from src.source_assets.schema.source_asset_model import AssetScopeEnum
from src.users.user_model import UserModel, UserRoleEnum


async def owned_media_item(media_repo, item_id, workspace_id: int):
    """Fetch a MediaItem by id; return None unless it belongs to workspace_id.
    Matches gallery_service.get_media_by_id's workspace-membership model."""
    if item_id is None:
        return None
    item = await media_repo.get_by_id(item_id)
    if item is None:
        return None
    if item.workspace_id != workspace_id:
        return None
    return item


async def owned_source_asset(source_asset_repo, asset_id, user: UserModel):
    """Fetch a SourceAsset by id; return None unless the caller is the
    uploader, an admin, or the asset is SYSTEM-scoped (shared, e.g. VTO
    model assets). Matches source_asset_service.get_asset_by_id's existing
    owner-private model exactly -- workspace membership alone is NOT
    sufficient, same as /source_assets/search and GET /{asset_id}."""
    if asset_id is None:
        return None
    asset = await source_asset_repo.get_by_id(asset_id)
    if asset is None:
        return None
    is_admin = UserRoleEnum.ADMIN in user.roles
    is_owner = asset.user_id == user.id
    is_system = asset.scope == AssetScopeEnum.SYSTEM
    if not (is_admin or is_owner or is_system):
        return None
    return asset
