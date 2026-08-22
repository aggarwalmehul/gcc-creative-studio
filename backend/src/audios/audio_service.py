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
"""Service for audio generation and analysis."""

import asyncio
import base64
import io
import logging
import os
import sys
import time
import wave
from collections.abc import MutableSequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import vertexai
from fastapi import Depends
from google.cloud import aiplatform
from google.cloud import texttospeech_v1beta1 as texttospeech
from google.cloud.logging import Client as LoggerClient
from google.cloud.logging.handlers import CloudLoggingHandler
from google.genai import types
from google.protobuf import json_format, struct_pb2

from src.audios.audio_constants import LanguageEnum, VoiceEnum
from src.audios.dto.create_audio_dto import CreateAudioDto
from src.auth.iam_signer_credentials_service import IamSignerCredentials
from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
    MimeTypeEnum,
)
from src.common.schema.genai_model_setup import GenAIModelSetup
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)  # LYRIA_3_PRO_UPGRADE_V1
from src.common.schema.media_item_model import JobStatusEnum, MediaItemModel
from src.common.storage_service import GcsService
from src.config.config_service import config_service
from src.galleries.dto.gallery_response_dto import MediaItemResponse
from src.images.repository.media_item_repository import MediaRepository
from src.users.user_model import UserModel

logger = logging.getLogger(__name__)


def _process_audio_in_background(
    media_item_id: int,
    request_dto: CreateAudioDto,
    user_email: str,
    user_id: int,
):
    from src.common.token_logger import current_user_email
    from src.database import WorkerDatabase

    # AUDIO_WORKER_CONTEXTVAR_FIX_V1: ThreadPoolExecutor.submit() does NOT copy
    # contextvars.Context into the new thread, so current_user_email would
    # otherwise default to "unknown" here. user_email is already passed in
    # as a parameter (see call site).
    current_user_email.set(user_email or "unknown")

    worker_logger = logging.getLogger(f"audio_worker.{media_item_id}")
    worker_logger.setLevel(logging.INFO)

    try:
        if worker_logger.hasHandlers():
            worker_logger.handlers.clear()

        if os.getenv("ENVIRONMENT") == "production":
            log_client = LoggerClient()
            handler = CloudLoggingHandler(
                log_client,
                name=f"audio_worker.{media_item_id}",
            )
            worker_logger.addHandler(handler)
        else:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - [AUDIO_WORKER] - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            worker_logger.addHandler(handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _async_worker():
            async with WorkerDatabase() as db_factory:
                async with db_factory() as db:
                    media_repo = MediaRepository(db)
                    gcs_service = GcsService()
                    cfg = config_service

                    try:
                        vertexai.init(
                            project=cfg.PROJECT_ID, location=cfg.REGIONAL_LOCATION
                        )
                        start_time = time.monotonic()

                        permanent_gcs_uris = []
                        uid_short = str(user_id)[:4]

                        if request_dto.model in AudioService.GEMINI_MODELS:
                            client = GenAIModelSetup.init()

                            async def generate_gemini(index: int) -> str | None:
                                try:
                                    voice_name = (
                                        request_dto.voice_name.value
                                        if request_dto.voice_name
                                        else VoiceEnum.PUCK.value
                                    )
                                    response = client.models.generate_content(
                                        model=request_dto.model.value,
                                        contents=[
                                            (
                                                "Please read the following text: \n"
                                                + request_dto.prompt
                                            )
                                        ],
                                        config=types.GenerateContentConfig(
                                            response_modalities=["AUDIO"],
                                            audio_timestamp=False,
                                            speech_config=types.SpeechConfig(
                                                voice_config=types.VoiceConfig(
                                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                                        voice_name=voice_name,
                                                    ),
                                                ),
                                            ),
                                        ),
                                    )
                                    if (
                                        not response.candidates
                                        or not response.candidates[0].content
                                        or not response.candidates[
                                            0
                                        ].content.parts
                                    ):
                                        return None
                                    part = response.candidates[0].content.parts[
                                        0
                                    ]
                                    pcm_bytes = None
                                    if (
                                        hasattr(part, "inline_data")
                                        and part.inline_data
                                    ):
                                        pcm_bytes = part.inline_data.data
                                        if isinstance(pcm_bytes, str):
                                            pcm_bytes = base64.b64decode(
                                                pcm_bytes
                                            )
                                    if not pcm_bytes:
                                        return None
                                    wav_buffer = io.BytesIO()
                                    with wave.open(
                                        wav_buffer, "wb"
                                    ) as wav_file:
                                        wav_file.setnchannels(1)
                                        wav_file.setsampwidth(2)
                                        wav_file.setframerate(24000)
                                        wav_file.writeframes(pcm_bytes)
                                    final_wav_bytes = wav_buffer.getvalue()
                                    file_name = f"gemini_audio_{request_dto.model.value}_{media_item_id}_{uid_short}_{index}.wav"
                                    return gcs_service.store_to_gcs(
                                        folder="gemini_audio",
                                        file_name=file_name,
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        contents=final_wav_bytes,
                                        decode=False,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"Gemini generation error: {e}"
                                    )
                                    return None

                            tasks = [
                                generate_gemini(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]

                        elif request_dto.model in AudioService.TTS_MODELS:
                            tts_client = texttospeech.TextToSpeechClient()

                            async def generate_tts(index: int) -> str | None:
                                try:
                                    synthesis_input = (
                                        texttospeech.SynthesisInput(
                                            text=request_dto.prompt
                                        )
                                    )
                                    voice_name = (
                                        request_dto.voice_name.value
                                        if request_dto.voice_name
                                        else VoiceEnum.PUCK.value
                                    )
                                    language_code = (
                                        request_dto.language_code.value
                                        if request_dto.language_code
                                        else LanguageEnum.EN_US.value
                                    )
                                    if (
                                        request_dto.model
                                        == GenerationModelEnum.CHIRP_3
                                    ):
                                        voice_name = f"{language_code}-Chirp3-HD-{voice_name}"
                                    voice_params = (
                                        texttospeech.VoiceSelectionParams(
                                            language_code=language_code,
                                            name=voice_name,
                                        )
                                    )
                                    audio_config = texttospeech.AudioConfig(
                                        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                                        speaking_rate=1.0,
                                        volume_gain_db=0.0,
                                    )
                                    response = await asyncio.to_thread(
                                        tts_client.synthesize_speech,
                                        input=synthesis_input,
                                        voice=voice_params,
                                        audio_config=audio_config,
                                    )
                                    file_name = f"tts_{request_dto.model.value}_{media_item_id}_{uid_short}_{index}.wav"
                                    return gcs_service.store_to_gcs(
                                        folder="tts_audio",
                                        file_name=file_name,
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        contents=response.audio_content,
                                        decode=False,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"TTS generation error: {e}"
                                    )
                                    return None

                            tasks = [
                                generate_tts(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]

                        elif request_dto.model in AudioService.MUSIC_MODELS:
                            client_options = {
                                "api_endpoint": "us-central1-aiplatform.googleapis.com"
                            }
                            ai_client = (
                                aiplatform.gapic.PredictionServiceClient(
                                    client_options=client_options
                                )
                            )

                            async def generate_music(index: int) -> str | None:
                                try:
                                    parameters_dict = {"sample_count": 1}
                                    parameters_value = struct_pb2.Value()
                                    json_format.ParseDict(
                                        parameters_dict, parameters_value
                                    )

                                    instance_dict = {
                                        "prompt": request_dto.prompt
                                    }
                                    if request_dto.negative_prompt:
                                        instance_dict["negative_prompt"] = (
                                            request_dto.negative_prompt
                                        )
                                    if request_dto.seed:
                                        instance_dict["seed"] = request_dto.seed

                                    instance_value = struct_pb2.Value()
                                    json_format.ParseDict(
                                        instance_dict, instance_value
                                    )

                                    endpoint = f"projects/{cfg.PROJECT_ID}/locations/global/publishers/google/models/lyria-002"
                                    response = await asyncio.to_thread(
                                        ai_client.predict,
                                        endpoint=endpoint,
                                        instances=[instance_value],
                                        parameters=parameters_value,
                                    )
                                    if not response.predictions:
                                        return None
                                    audio_b64 = response.predictions[0].get(
                                        "bytesBase64Encoded"
                                    )
                                    if not audio_b64:
                                        return None

                                    file_name = f"lyria_music_{media_item_id}_{uid_short}_{index}.wav"
                                    return gcs_service.store_to_gcs(
                                        folder="lyria_audio",
                                        file_name=file_name,
                                        mime_type=MimeTypeEnum.AUDIO_WAV,
                                        contents=base64.b64decode(audio_b64),
                                        decode=False,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"Lyria generation error: {e}"
                                    )
                                    return None

                            tasks = [
                                generate_music(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]

                        elif (
                            request_dto.model in AudioService.MUSIC_MODELS_V3
                        ):
                            # LYRIA_3_PRO_UPGRADE_V1: Lyria 3 Pro uses the modern
                            # Interactions API (same client/pattern as Gemini
                            # Omni video), not the legacy Prediction API used
                            # by Lyria 2. Genuinely new capabilities: duration
                            # up to 184s, lyrics, instrumental mode, and
                            # image-to-music -- all steered via the prompt
                            # text plus optional reference images, per
                            # Google's documented Lyria 3 Pro usage pattern.
                            vertex_client = GenAIModelSetup.get_omni_client()

                            # Resolve reference images. Two sources are
                            # supported, mirroring the exact dual-path
                            # pattern already used for Veo/Omni reference
                            # images in veo_service.py:
                            #   1. reference_image_asset_ids -> directly
                            #      uploaded SourceAsset rows.
                            #   2. reference_media_items -> previously
                            #      generated gallery MediaItem rows
                            #      (resolved via media_item_id + media_index
                            #      into one of that item's gcs_uris).
                            # LYRIA_REF_IMAGE_FIX_V1: the image-selector dialog
                            # can return either kind, so both must be
                            # resolved correctly rather than assuming a
                            # single flat SourceAsset-only shape.
                            lyria_reference_images: list[dict] = []
                            if request_dto.reference_image_asset_ids:
                                source_asset_repo = SourceAssetRepository(db)
                                for (
                                    asset_id
                                ) in request_dto.reference_image_asset_ids:
                                    asset = await source_asset_repo.get_by_id(
                                        asset_id,
                                    )
                                    if asset and asset.gcs_uri:
                                        lyria_reference_images.append(
                                            {
                                                "type": "image",
                                                "mime_type": asset.mime_type,
                                                "uri": asset.gcs_uri,
                                            },
                                        )
                            if request_dto.reference_media_items:
                                for (
                                    ref_item
                                ) in request_dto.reference_media_items:
                                    parent_item = await media_repo.get_by_id(
                                        ref_item.media_item_id,
                                    )
                                    if (
                                        parent_item
                                        and parent_item.gcs_uris
                                        and 0
                                        <= ref_item.media_index
                                        < len(parent_item.gcs_uris)
                                    ):
                                        lyria_reference_images.append(
                                            {
                                                "type": "image",
                                                "mime_type": parent_item.mime_type,
                                                "uri": parent_item.gcs_uris[
                                                    ref_item.media_index
                                                ],
                                            },
                                        )

                            # Compose the prompt: Lyria 3 Pro is almost
                            # entirely prompt-driven (duration, instrumental
                            # mode, and lyrics are all specified as natural
                            # language instructions in the prompt text).
                            composed_prompt_parts = [request_dto.prompt]
                            if request_dto.duration_seconds:
                                composed_prompt_parts.append(
                                    f"Make this song approximately "
                                    f"{request_dto.duration_seconds} seconds "
                                    f"long.",
                                )
                            if request_dto.instrumental:
                                composed_prompt_parts.append(
                                    "This should be a purely instrumental "
                                    "track with no vocals or lyrics.",
                                )
                            elif request_dto.lyrics:
                                composed_prompt_parts.append(
                                    f"Use the following lyrics for the "
                                    f"vocals:\n{request_dto.lyrics}",
                                )
                            composed_prompt = " ".join(
                                composed_prompt_parts,
                            )

                            lyria_inputs: list[dict] = [
                                {"type": "text", "text": composed_prompt},
                            ]
                            lyria_inputs.extend(lyria_reference_images)

                            async def generate_music_v3(
                                index: int,
                            ) -> str | None:
                                try:
                                    interaction = await asyncio.to_thread(
                                        vertex_client.interactions.create,
                                        # LYRIA_3_CLIP_UPGRADE_V1: use whichever
                                        # Lyria 3 variant was requested
                                        # (Pro or Clip) instead of hardcoding
                                        # Pro -- both share this code path.
                                        model=request_dto.model.value,
                                        input=lyria_inputs,
                                        stream=False,
                                    )

                                    generated_audio = getattr(
                                        interaction, "output_audio", None,
                                    )
                                    if (
                                        not generated_audio
                                        or not generated_audio.data
                                    ):
                                        worker_logger.error(
                                            "Lyria 3 Pro returned no audio "
                                            "output.",
                                        )
                                        return None

                                    audio_bytes = base64.b64decode(
                                        generated_audio.data,
                                    )
                                    file_name = (
                                        f"lyria3pro_music_{media_item_id}_"
                                        f"{uid_short}_{index}.mp3"
                                    )
                                    return gcs_service.store_to_gcs(
                                        folder="lyria_audio",
                                        file_name=file_name,
                                        mime_type=MimeTypeEnum.AUDIO_MP3,
                                        contents=audio_bytes,
                                        decode=False,
                                    )
                                except Exception as e:
                                    worker_logger.error(
                                        f"Lyria 3 Pro generation error: {e}",
                                    )
                                    return None

                            # Lyria 3 Pro returns exactly one clip per API
                            # call (unlike Lyria 2's single-call sample_count),
                            # so we issue sample_count separate calls in
                            # parallel, same asyncio.gather pattern as above.
                            tasks = [
                                generate_music_v3(i)
                                for i in range(request_dto.sample_count)
                            ]
                            results = await asyncio.gather(*tasks)
                            permanent_gcs_uris = [u for u in results if u]

                        else:
                            raise ValueError(
                                f"Model {request_dto.model} is not supported."
                            )

                        if not permanent_gcs_uris:
                            raise ValueError(
                                "Failed to generate any audio samples."
                            )

                        generation_time = time.monotonic() - start_time

                        await media_repo.update(
                            media_item_id,
                            {
                                "status": JobStatusEnum.COMPLETED,
                                "gcs_uris": permanent_gcs_uris,
                                "generation_time": generation_time,
                            },
                        )
                        worker_logger.info(
                            f"Audio job {media_item_id} completed successfully."
                        )

                    except Exception as e:
                        worker_logger.error(
                            f"Audio processing failed: {e}", exc_info=True
                        )
                        await media_repo.update(
                            media_item_id,
                            {
                                "status": JobStatusEnum.FAILED,
                                "error_message": str(e),
                            },
                        )

        loop.run_until_complete(_async_worker())
    except Exception as outer_e:
        worker_logger.error(
            f"Fatal error in worker thread: {outer_e}", exc_info=True
        )


class AudioService:
    GEMINI_MODELS = {
        GenerationModelEnum.GEMINI_2_5_FLASH_TTS,
        GenerationModelEnum.GEMINI_2_5_FLASH_LITE_PREVIEW_TTS,
        GenerationModelEnum.GEMINI_2_5_PRO_TTS,
        GenerationModelEnum.GEMINI_3_1_FLASH_TTS,  # GEMINI_3_1_TTS_UPGRADE_V1
    }
    TTS_MODELS = {
        GenerationModelEnum.CHIRP_3,
    }
    MUSIC_MODELS = {
        GenerationModelEnum.LYRIA_002,
    }
    MUSIC_MODELS_V3 = {  # LYRIA_3_PRO_UPGRADE_V1
        GenerationModelEnum.LYRIA_3_PRO,
        GenerationModelEnum.LYRIA_3_CLIP,  # LYRIA_3_CLIP_UPGRADE_V1
    }

    def __init__(
        self,
        media_repo: MediaRepository = Depends(),
        iam_signer_credentials: IamSignerCredentials = Depends(),
    ):
        self.iam_signer_credentials = iam_signer_credentials
        self.media_repo = media_repo

    async def start_audio_generation_job(
        self,
        request_dto: CreateAudioDto,
        user: UserModel,
        executor: ThreadPoolExecutor,
    ) -> MediaItemResponse:

        # LYRIA_3_PRO_UPGRADE_V1: stash Lyria 3 Pro-specific fields in the
        # generic raw_data JSONB column (no schema migration needed), same
        # pattern already used for VEO concatenation inputs and brand
        # guideline interaction metadata elsewhere in the codebase.
        is_lyria_3_pro = (
            request_dto.model == GenerationModelEnum.LYRIA_3_PRO
        )
        lyria_3_pro_raw_data = (
            {
                "duration_seconds": request_dto.duration_seconds,
                "lyrics": request_dto.lyrics,
                "instrumental": request_dto.instrumental,
                "reference_image_asset_ids": (
                    request_dto.reference_image_asset_ids
                ),
            }
            if is_lyria_3_pro
            else {}
        )

        media_post_to_save = MediaItemModel(
            user_email=user.email,
            user_id=user.id,
            mime_type=(
                MimeTypeEnum.AUDIO_MP3
                if is_lyria_3_pro
                else MimeTypeEnum.AUDIO_WAV
            ),
            model=request_dto.model,
            aspect_ratio=AspectRatioEnum.RATIO_16_9,
            workspace_id=request_dto.workspace_id,
            prompt=request_dto.prompt,
            original_prompt=request_dto.prompt,
            num_media=request_dto.sample_count,
            status=JobStatusEnum.PROCESSING,
            negative_prompt=request_dto.negative_prompt,
            voice_name=request_dto.voice_name,
            language_code=request_dto.language_code,
            seed=request_dto.seed,
            gcs_uris=[],
            raw_data=lyria_3_pro_raw_data,
        )
        saved_item = await self.media_repo.create(media_post_to_save)

        executor.submit(
            _process_audio_in_background,
            saved_item.id,
            request_dto,
            user.email,
            user.id,
        )

        return MediaItemResponse(
            **saved_item.model_dump(),
            presigned_urls=[],
        )
