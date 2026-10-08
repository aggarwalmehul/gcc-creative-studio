"""Cloud Tasks enqueue helper for async media post-processing.

Ported from vertex-ai-creative-studio's async-thumbnail pattern (see
creative-studio-repo-comparison.md, section 8). Adapted to this repo's
actual config_service singleton and the already-pinned google-cloud-tasks
dependency (>=2.0.0 in pyproject.toml).
"""

import json
import logging
from os import getenv

from google.cloud import tasks_v2

from src.config.config_service import config_service

logger = logging.getLogger(__name__)

# FEATURE_PORT_CLOUD_TASKS_THUMBNAILS_V1: reuse the existing SIGNING_SA_EMAIL identity (already
# granted roles/iam.serviceAccountTokenCreator, already the codebase's
# established "identity used for signing operations" -- see
# iam_signer_credentials_service.py) as the Cloud Tasks OIDC invoker,
# rather than the unset BACKEND_SERVICE_ACCOUNT_EMAIL or the broad,
# already-overloaded compute default SA. Read the same way that file
# reads it: via os.getenv, NOT through config_service (it is
# intentionally not a Pydantic settings field).
_SIGNING_SA_EMAIL = getenv("SIGNING_SA_EMAIL", "")


def enqueue_thumbnail_task(
    video_gcs_uri: str,
    media_item_id: int,
    media_index: int,
) -> bool:
    """Enqueues a Cloud Task to generate a thumbnail out-of-band.

    Fire-and-forget from the caller's perspective: returns False (and logs
    a warning) rather than raising, so a Cloud Tasks outage never breaks
    the video-generation happy path. Callers should treat a False return
    the same as "no thumbnail yet" -- gallery_service.py already tolerates
    a missing thumbnail_gcs_uri.
    """
    try:
        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            config_service.PROJECT_ID,
            config_service.TASKS_LOCATION,
            config_service.TASKS_QUEUE_ID,
        )
        payload = {
            "video_gcs_uri": video_gcs_uri,
            "media_item_id": media_item_id,
            "media_index": media_index,
        }
        http_request: dict = {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": config_service.TASKS_WORKER_URL,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode(),
        }
        if _SIGNING_SA_EMAIL:
            http_request["oidc_token"] = {
                "service_account_email": _SIGNING_SA_EMAIL,
                "audience": config_service.TASKS_WORKER_URL,
            }
        else:
            logger.warning(
                "THUMBTASK: SIGNING_SA_EMAIL not set -- enqueueing task "
                "WITHOUT an OIDC token (worker will reject it)."
            )
        task = {"http_request": http_request}
        client.create_task(request={"parent": parent, "task": task})
        logger.info(
            "THUMBTASK: enqueued for media_item=%s idx=%s",
            media_item_id,
            media_index,
        )
        return True
    except Exception as e:  # noqa: BLE001 -- never break the video worker
        logger.warning(
            "THUMBTASK: enqueue failed for media_item=%s idx=%s (%s); "
            "thumbnail will remain empty until manually retried",
            media_item_id,
            media_index,
            e,
        )
        return False
