"""OUTPUT_FOLDER_V1: ported from upstream. Picks the gallery folder a new
media item is saved into. An explicit folder_id wins, then the Izumi agent
folder, then the workspace root (None). An explicit folder must exist, must
not be soft-deleted and must belong to the request's workspace; missing,
deleted and foreign folders share one error so ids can't be enumerated.
"""
import logging

from fastapi import HTTPException

from src.folders.agent_output_folder import resolve_agent_output_folder_id
from src.folders.repository.folder_repository import FolderRepository

logger = logging.getLogger(__name__)

OUTPUT_FOLDER_NOT_FOUND_DETAIL = "The selected output folder was not found in this workspace."


async def resolve_output_folder_id(db, workspace_id: int, user, requested_folder_id: int | None) -> int | None:
    if requested_folder_id is None:
        return await resolve_agent_output_folder_id(db, workspace_id, user)
    folder = await FolderRepository(db).get_folder_by_id(requested_folder_id)
    if (
        folder is None
        or getattr(folder, "deleted_at", None) is not None
        or folder.workspace_id != workspace_id
    ):
        logger.warning("User %s requested output folder %s, not an active folder of workspace %s",
                       getattr(user, "id", None), requested_folder_id, workspace_id)
        raise HTTPException(status_code=422, detail=OUTPUT_FOLDER_NOT_FOUND_DETAIL)
    return requested_folder_id
