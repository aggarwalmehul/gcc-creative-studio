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

from typing import Annotated

from fastapi import Query
from pydantic import Field, field_validator, model_validator

from src.audios.audio_constants import LanguageEnum, VoiceEnum
from src.common.base_dto import BaseDto, GenerationModelEnum


class CreateAudioDto(BaseDto):
    """Generic Audio Generation DTO.
    Supports:
    1. Music Generation (Lyria) -> Uses negative_prompt, sample_count, seed
    2. Text-to-Speech (Chirp, Gemini TTS) -> Uses language_code, voice_name
    """

    model: GenerationModelEnum = Field(
        default=GenerationModelEnum.LYRIA_002,
        description="The model to use for generation (Lyria, Chirp, Gemini TTS).",
    )

    prompt: Annotated[str, Query(max_length=10000)] = Field(
        description="The text input. For Lyria, this is the music description. For TTS, this is the text to speak.",
    )

    workspace_id: int = Field(
        description="The ID of the workspace for this generation.",
    )

    # --- Lyria Specific Fields ---
    negative_prompt: str | None = Field(
        default=None,
        description="[Lyria Only] What to avoid in the music generation.",
    )

    sample_count: int = Field(
        default=1,
        ge=1,
        le=4,
        description="[Lyria Only] Number of audio samples to generate.",
    )

    seed: int | None = Field(
        default=None,
        description="[Lyria Only] A seed for deterministic generation.",
    )

    # --- Lyria 3 Pro Specific Fields (LYRIA_3_PRO_UPGRADE_V1) ---
    duration_seconds: int | None = Field(
        default=None,
        ge=1,
        le=184,
        description="[Lyria 3 Pro Only] Desired song duration in seconds (max 184).",
    )

    lyrics: str | None = Field(
        default=None,
        max_length=5000,
        description="[Lyria 3 Pro Only] User-provided lyrics to guide the track. Ignored if instrumental=True.",
    )

    instrumental: bool = Field(
        default=False,
        description="[Lyria 3 Pro Only] If true, generates an instrumental track with no vocals.",
    )

    reference_image_asset_ids: list[int] | None = Field(
        default=None,
        max_length=10,
        description="[Lyria 3 Pro Only] Up to 10 SourceAsset IDs to use as visual inspiration (image-to-music).",
    )

    # --- TTS / Chirp Specific Fields ---
    language_code: LanguageEnum | None = Field(
        default=LanguageEnum.EN_US,
        description="The BCP-47 language code.",
    )

    # 2. FLEXIBLE TYPING (Validated conditionally below):
    voice_name: VoiceEnum | None = Field(
        default=VoiceEnum.PUCK,
        description="The specific voice ID. For Gemini, must be a valid GeminiVoiceEnum value.",
    )

    @field_validator("model")
    def validate_audio_model(
        cls, value: GenerationModelEnum
    ) -> GenerationModelEnum:
        allowed_audio_models = {
            GenerationModelEnum.LYRIA_002,
            GenerationModelEnum.LYRIA_3_PRO,  # LYRIA_3_PRO_UPGRADE_V1
            GenerationModelEnum.CHIRP_3,
            GenerationModelEnum.GEMINI_2_5_FLASH_TTS,
            GenerationModelEnum.GEMINI_2_5_FLASH_LITE_PREVIEW_TTS,
            GenerationModelEnum.GEMINI_2_5_PRO_TTS,
        }

        if value not in allowed_audio_models:
            raise ValueError(
                f"Model '{value}' is not a valid audio model. "
                f"Allowed models: {[m.value for m in allowed_audio_models]}",
            )
        return value

    @model_validator(mode="after")
    def validate_model_requirements(self) -> "CreateAudioDto":
        model_str = str(self.model).lower()

        is_music_model = "lyria" in model_str

        if not is_music_model:
            # TTS Check
            if not self.language_code:
                raise ValueError(
                    "language_code is required for Text-to-Speech models."
                )

        # LYRIA_3_PRO_UPGRADE_V1: Lyria 3 Pro does not support negative prompting,
        # and its new fields (duration/lyrics/instrumental/reference images)
        # only apply to Lyria 3 Pro, not Lyria 2 or TTS models.
        is_lyria_3_pro = self.model == GenerationModelEnum.LYRIA_3_PRO
        if is_lyria_3_pro and self.negative_prompt:
            raise ValueError(
                "negative_prompt is not supported by Lyria 3 Pro."
            )
        if not is_lyria_3_pro and (
            self.duration_seconds
            or self.lyrics
            or self.instrumental
            or self.reference_image_asset_ids
        ):
            raise ValueError(
                "duration_seconds, lyrics, instrumental, and "
                "reference_image_asset_ids are only supported by Lyria 3 Pro."
            )

        return self
