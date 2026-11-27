"""THINKING_TOKENS_V1: tokens beyond input + output (reasoning) must be counted as output."""
import types
from src.common import token_logger as tl


def ns(**kw):
    return types.SimpleNamespace(**kw)


def test_generate_content_shape_counts_the_gap_as_output():
    resp = ns(usage_metadata=ns(prompt_token_count=100, candidates_token_count=20, total_token_count=150))
    assert tl._normalize_usage(resp, "gemini-3.5-flash") == (100, 50, 150)


def test_interactions_shape_counts_the_gap_as_output():
    resp = ns(usage=ns(total_input_tokens=100, total_output_tokens=20, total_tokens=150))
    assert tl._normalize_usage(resp, "gemini-omni-1.2-flash") == (100, 50, 150)


def test_no_gap_changes_nothing():
    resp = ns(usage_metadata=ns(prompt_token_count=100, candidates_token_count=20, total_token_count=120))
    assert tl._normalize_usage(resp, "gemini-3.5-flash") == (100, 20, 120)


def test_missing_total_changes_nothing():
    resp = ns(usage_metadata=ns(prompt_token_count=100, candidates_token_count=20, total_token_count=0))
    assert tl._normalize_usage(resp, "gemini-3.5-flash") == (100, 20, 0)


def test_no_usage_returns_none():
    assert tl._normalize_usage(ns(), "gemini-3.5-flash") is None


def test_image_models_are_left_alone():
    resp = ns(usage_metadata=ns(prompt_token_count=100, candidates_token_count=20, total_token_count=150))
    for m in ("gemini-nano-banana-2.1", "gemini-3-pro-image", "gemini-3.1-flash-image", "gemini-2.5-flash-image"):
        assert tl._normalize_usage(resp, m) == (100, 20, 150), m


def test_default_model_argument_still_works():
    resp = ns(usage_metadata=ns(prompt_token_count=100, candidates_token_count=20, total_token_count=150))
    assert tl._normalize_usage(resp) == (100, 50, 150)
