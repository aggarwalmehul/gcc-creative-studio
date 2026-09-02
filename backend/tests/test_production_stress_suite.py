# Copyright 2026 Google LLC
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
"""Comprehensive Production Stress and Concurrency Test Suite for Creative Studio."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audios.audio_service import AudioService, _process_audio_in_background
from src.audios.dto.create_audio_dto import CreateAudioDto
from src.common.base_dto import (
    AspectRatioEnum,
    GenerationModelEnum,
)
from src.common.schema.media_item_model import (
    AssetRoleEnum,
    JobStatusEnum,
    MediaItemModel,
    MimeTypeEnum,
    SourceMediaItemLink,
)
from src.multimodal.gemini_service import GeminiService, PromptTargetEnum
from src.users.user_model import UserModel
from src.videos.dto.create_veo_dto import AssetReferenceDto, CreateVeoDto
from src.videos.veo_service import VeoService


@pytest.fixture
def mock_gemini_client():
    with patch("src.multimodal.gemini_service.GeminiModelSetup.init") as mock_init:
        client = MagicMock()
        mock_init.return_value = client
        yield client


@pytest.fixture
def mock_regional_client():
    with patch("src.videos.veo_service.GenAIModelSetup.init_regional") as mock_init:
        client = MagicMock()
        mock_init.return_value = client
        yield client


class TestFramesToVideoConsistencyStress:
    """Stress tests for Frames-to-Video consistency and prompt enhancement under load."""

    @pytest.mark.anyio
    async def test_concurrent_frames_to_video_enhancement(self, mock_gemini_client):
        """Test 100 concurrent requests enhancing Frames-to-Video prompts."""
        gemini_service = GeminiService()
        gemini_service.client = mock_gemini_client

        num_concurrent_requests = 100
        dtos = [
            CreateVeoDto(
                prompt=f"Subject {i} transforms smoothly across scene {i}",
                generation_model=GenerationModelEnum.VEO_3_1_GENERATE_001,
                start_image_asset_id=AssetReferenceDto(id=i * 2, type="source_asset"),
                end_image_asset_id=AssetReferenceDto(id=i * 2 + 1, type="source_asset"),
                workspace_id=1,
            )
            for i in range(num_concurrent_requests)
        ]

        start_time = time.perf_counter()
        results = await asyncio.gather(
            *[
                gemini_service.enhance_prompt_from_dto(dto, PromptTargetEnum.VIDEO)
                for dto in dtos
            ]
        )
        elapsed_time = time.perf_counter() - start_time

        assert len(results) == num_concurrent_requests
        for i, res in enumerate(results):
            assert "Strict Subject & Object Consistency" in res
            assert "between the provided START FRAME and END FRAME" in res
            assert f"Subject {i} transforms" in res

        assert elapsed_time < 2.0

    @pytest.mark.anyio
    async def test_frames_to_video_media_item_links_concurrency(self, mock_gemini_client):
        """Test concurrent Frames-to-Video requests using SourceMediaItemLinks."""
        gemini_service = GeminiService()
        gemini_service.client = mock_gemini_client

        num_concurrent_requests = 50
        dtos = [
            CreateVeoDto(
                prompt=f"Omni transition sequence {i}",
                generation_model=GenerationModelEnum.GEMINI_OMNI_FLASH_PREVIEW,
                source_media_items=[
                    SourceMediaItemLink(
                        media_item_id=100 + i, media_index=0, role=AssetRoleEnum.START_FRAME
                    ),
                    SourceMediaItemLink(
                        media_item_id=200 + i, media_index=0, role=AssetRoleEnum.END_FRAME
                    ),
                ],
                workspace_id=1,
            )
            for i in range(num_concurrent_requests)
        ]

        results = await asyncio.gather(
            *[
                gemini_service.enhance_prompt_from_dto(dto, PromptTargetEnum.VIDEO)
                for dto in dtos
            ]
        )

        assert len(results) == num_concurrent_requests
        for i, res in enumerate(results):
            assert "Strict Subject & Object Consistency" in res
            assert "Context & Environment Preservation" in res
            assert f"Omni transition sequence {i}" in res


class TestGeminiTtsStressAndConcurrency:
    """Stress tests for Gemini 3.1 Pro TTS and audio generation under load."""

    @pytest.mark.anyio
    async def test_concurrent_gemini_3_1_pro_tts_job_dispatch(self):
        """Test 50 concurrent Gemini 3.1 Pro TTS job dispatches."""
        mock_media_repo = AsyncMock()
        mock_media_repo.create = AsyncMock(
            side_effect=lambda item: MediaItemModel(
                id=item.id or 100,
                workspace_id=item.workspace_id,
                user_id=item.user_id,
                user_email=item.user_email,
                mime_type=MimeTypeEnum.AUDIO_WAV,
                model=item.model,
                aspect_ratio="16:9",
                gcs_uris=[],
                thumbnail_uris=[],
            )
        )

        audio_service = AudioService(
            media_repo=mock_media_repo,
            iam_signer_credentials=MagicMock(),
        )

        mock_user = UserModel(
            id=1, email="tester@example.com", name="Stress Tester", roles=["user"]
        )
        mock_executor = MagicMock()

        num_requests = 50
        tasks = []
        for i in range(num_requests):
            dto = CreateAudioDto(
                prompt=f"Welcome to the stress test iteration number {i}.",
                model=GenerationModelEnum.GEMINI_3_1_PRO_TTS,
                voice_name="Puck",
                workspace_id=1,
            )
            tasks.append(
                audio_service.start_audio_generation_job(
                    request_dto=dto,
                    user=mock_user,
                    executor=mock_executor,
                )
            )

        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed_time = time.perf_counter() - start_time

        assert len(results) == num_requests
        assert mock_media_repo.create.call_count == num_requests
        assert mock_executor.submit.call_count == num_requests
        assert elapsed_time < 3.0

    @pytest.mark.anyio
    async def test_gemini_tts_dto_validation_and_model_resolution(self):
        """Verify DTO validation under various model combinations."""
        # 1. Gemini 3.1 Pro TTS valid
        dto1 = CreateAudioDto(
            prompt="Test prompt 1",
            model=GenerationModelEnum.GEMINI_3_1_PRO_TTS,
            voice_name="Charon",
            workspace_id=1,
        )
        assert dto1.model == GenerationModelEnum.GEMINI_3_1_PRO_TTS

        # 2. Gemini 2.5 Pro TTS valid
        dto2 = CreateAudioDto(
            prompt="Test prompt 2",
            model=GenerationModelEnum.GEMINI_2_5_PRO_TTS,
            voice_name="Kore",
            workspace_id=1,
        )
        assert dto2.model == GenerationModelEnum.GEMINI_2_5_PRO_TTS

        # 3. Gemini 2.5 Flash TTS valid
        dto3 = CreateAudioDto(
            prompt="Test prompt 3",
            model=GenerationModelEnum.GEMINI_2_5_FLASH_TTS,
            voice_name="Fenrir",
            workspace_id=1,
        )
        assert dto3.model == GenerationModelEnum.GEMINI_2_5_FLASH_TTS


class TestResilienceAndRecoveryUnderLoad:
    """Stress tests for worker background processing, database concurrency, and error handling."""

    @patch("src.database.WorkerDatabase")
    @patch("src.audios.audio_service.MediaRepository")
    @patch("src.audios.audio_service.GenAIModelSetup")
    @patch("src.audios.audio_service.GcsService")
    def test_worker_gemini_3_1_pro_tts_background_processing(
        self,
        mock_gcs,
        mock_genai,
        mock_repo_cls,
        mock_worker_db,
    ):
        """Assert that background worker handles Gemini 3.1 Pro TTS generation and updates DB."""
        # Mock WorkerDatabase
        mock_db_factory = MagicMock()
        mock_worker_db.return_value.__aenter__.return_value = mock_db_factory
        mock_db_session = AsyncMock()
        mock_db_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock MediaRepository
        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        # Mock GcsService
        mock_gcs_singleton = MagicMock()
        mock_gcs_singleton.store_to_gcs.return_value = "gs://bucket/gemini_audio_output.wav"
        mock_gcs.return_value = mock_gcs_singleton

        # Mock GenAI SDK client
        mock_client = MagicMock()
        mock_genai.init.return_value = mock_client
        mock_content = MagicMock()
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = "SGVsbG8="  # Base64 data
        mock_content.parts = [mock_part]

        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_client.models.generate_content.return_value = MagicMock(
            candidates=[mock_candidate]
        )

        sample_dto = CreateAudioDto(
            prompt="Speaking with Gemini 3.1 Pro TTS under stress testing",
            model=GenerationModelEnum.GEMINI_3_1_PRO_TTS,
            voice_name="Aoede",
            sample_count=1,
            workspace_id=1,
        )

        _process_audio_in_background(
            media_item_id=777,
            request_dto=sample_dto,
            user_email="tester@example.com",
            user_id=1,
        )

        # Assert DB update
        mock_repo.update.assert_called_with(
            777,
            {
                "status": JobStatusEnum.COMPLETED,
                "gcs_uris": ["gs://bucket/gemini_audio_output.wav"],
                "generation_time": pytest.approx(0, abs=10.0),
            },
        )
