"""VEO_NOAUDIO_BILLING_V1: no-audio full Veo 3.1 is billed at half the with-audio rate."""
import types
from src.common.token_logger import billing_model_key


def test_full_veo_without_audio_gets_its_own_key():
    assert billing_model_key("veo-3.1-generate-001", False) == "veo-3.1-generate-001-noaudio"


def test_full_veo_with_audio_is_unchanged():
    assert billing_model_key("veo-3.1-generate-001", True) == "veo-3.1-generate-001"


def test_unknown_audio_flag_counts_as_audio():
    assert billing_model_key("veo-3.1-generate-001", None) == "veo-3.1-generate-001"


def test_fast_and_omni_are_unchanged():
    for m in ("veo-3.1-fast-generate-001", "gemini-omni-1.2-flash"):
        assert billing_model_key(m, False) == m


def test_enum_members_are_unwrapped():
    e = types.SimpleNamespace(value="veo-3.1-generate-001")
    assert billing_model_key(e, False) == "veo-3.1-generate-001-noaudio"
