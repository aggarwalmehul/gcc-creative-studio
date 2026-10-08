"""Cloud Run worker endpoint invoked by Cloud Tasks to generate a video's
thumbnail out-of-band.
"""

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.task_auth import verify_cloud_tasks_oidc
from src.common.media_utils import generate_thumbnail
from src.common.storage_service import GcsService
from src.images.repository.media_item_repository import MediaRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/tasks",
    tags=["Internal - Cloud Tasks Workers"],
)


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    """Splits a gs://bucket/path/to/blob URI into (bucket, blob_path)."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Not a valid GCS URI: {gcs_uri}")
    without_scheme = gcs_uri[len("gs://") :]
    bucket, _, blob_path = without_scheme.partition("/")
    if not bucket or not blob_path:
        raise ValueError(f"Malformed GCS URI: {gcs_uri}")
    return bucket, blob_path


@router.post("/generate-thumbnail")
async def generate_thumbnail_task(
    request: Request,
    media_repo: MediaRepository = Depends(),
    _claims: dict = Depends(verify_cloud_tasks_oidc),
):
    """Cloud Tasks push-target: downloads the already-uploaded video,
    generates a thumbnail via the existing ffmpeg helper, uploads it, and
    writes it back into media_item.thumbnail_uris[media_index].
    """
    body = await request.json()
    video_gcs_uri = body.get("video_gcs_uri")
    media_item_id = body.get("media_item_id")
    media_index = body.get("media_index")

    if not video_gcs_uri or media_item_id is None or media_index is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "video_gcs_uri, media_item_id, and media_index are "
                "required."
            ),
        )

    local_video_path = f"thumbnails/async_src_{media_item_id}_{media_index}.mp4"
    local_thumbnail_path = ""
    try:
        bucket_name, video_blob_path = _parse_gcs_uri(video_gcs_uri)
        gcs_service = GcsService(bucket_name=bucket_name)

        os.makedirs(os.path.dirname(local_video_path) or ".", exist_ok=True)
        downloaded = await asyncio.to_thread(
            gcs_service.download_from_gcs,
            video_blob_path,
            local_video_path,
        )
        if not downloaded:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to download video from {video_gcs_uri}.",
            )

        local_thumbnail_path = await asyncio.to_thread(
            generate_thumbnail, local_video_path
        )
        if not local_thumbnail_path:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="generate_thumbnail returned no output.",
            )

        thumbnail_gcs_blob = f"thumbnails/{media_item_id}_{media_index}.png"
        thumbnail_gcs_uri = await asyncio.to_thread(
            gcs_service.upload_file_to_gcs,
            local_path=local_thumbnail_path,
            destination_blob_name=thumbnail_gcs_blob,
            mime_type="image/png",
        )
        if not thumbnail_gcs_uri:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload thumbnail to GCS.",
            )

        item = await media_repo.get_by_id(media_item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"media_item_id {media_item_id} not found.",
            )
        current_uris = list(item.thumbnail_uris or [])
        while len(current_uris) <= media_index:
            current_uris.append("")
        current_uris[media_index] = thumbnail_gcs_uri
        await media_repo.update(media_item_id, {"thumbnail_uris": current_uris})

        logger.info(
            "THUMBWORK: done media_item=%s idx=%s",
            media_item_id,
            media_index,
        )
        return {"status": "ok", "thumbnail_gcs_uri": thumbnail_gcs_uri}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 -- non-2xx makes Cloud Tasks retry
        logger.error(
            "THUMBWORK: failed media_item=%s idx=%s err=%s",
            media_item_id,
            media_index,
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    finally:
        for path in [local_video_path, local_thumbnail_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as cleanup_err:  # noqa: BLE001
                    logger.warning(
                        "THUMBWORK: cleanup failed for %s: %s",
                        path,
                        cleanup_err,
                    )
