"""Shared pricing logic for admin cost reporting.

PRICING_ADMIN_DASHBOARD_V1: a direct, faithful port of the cost calculation
functions from genai-token-report (~/token-report-extract/app/main.py), so
the Admin Console's cost figures match the (currently undeliverable, due to
the SendGrid outage) email reports exactly, rather than maintaining a
second, potentially-diverging pricing engine.
"""
import json
import logging

logger = logging.getLogger(__name__)

_PRICING_URI = "gs://ltm-craftstudio-poc-genflow-bucket/config/pricing.json"
_FALLBACK = {
    "usd_to_inr": 84,
    "default": {"input": 0.50, "output": 1.50},
    "models": {},
    "billing_units": {},
    "budgets_usd_per_day": {},
}

_cached_pricing: dict | None = None


def load_pricing() -> dict:
    """Loads pricing.json from GCS, with an in-process cache.

    Falls back to a safe default if the file can't be read, mirroring
    genai-token-report's own behavior (never raises).
    """
    global _cached_pricing
    if _cached_pricing is not None:
        return _cached_pricing
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket_name, _, blob_path = _PRICING_URI.replace("gs://", "").partition("/")
        content = client.bucket(bucket_name).blob(blob_path).download_as_text()
        _cached_pricing = json.loads(content)
    except Exception as e:
        logger.warning("pricing load failed: %s", e)
        _cached_pricing = _FALLBACK
    return _cached_pricing


def _rate_on(entry: dict, at) -> dict:
    """DATE_AWARE_PRICING_V1: returns the input/output rate in effect on
    `at` (a date/datetime or ISO string). The entry's flat input/output keys
    are the base rate; an optional "rates" list of {"from": "YYYY-MM-DD",
    "input": x, "output": y} overrides it from each date onward. Flat keys
    are kept so genai-token-report (which only reads them) still works.
    """
    rate = {"input": entry["input"], "output": entry["output"]}
    if at is None or not entry.get("rates"):
        return rate
    day = str(at)[:10]
    for r in sorted(entry["rates"], key=lambda r: r["from"]):
        if r["from"] <= day:
            rate = {"input": r["input"], "output": r["output"]}
    return rate


def cost_usd(pricing: dict, model: str, tokens_in: float, tokens_out: float, at=None) -> float:
    """Token-based cost, in USD, at the rate in effect on `at` (defaults to
    the base rate). Unlisted models use the 'default' rate."""
    m = pricing.get("models", {}).get(
        model, pricing.get("default", {"input": 0.5, "output": 1.5})
    )
    r = _rate_on(m, at)
    return (tokens_in / 1_000_000) * r["input"] + (tokens_out / 1_000_000) * r["output"]


def cost_units_usd(pricing: dict, model: str, unit_type: str, quantity: float) -> float:
    """Native-unit media cost (Veo seconds, Chirp characters, Lyria
    generations), in USD. Prices ONLY models explicitly listed in
    pricing['billing_units'] with a matching unit_type -- everything else
    (including a unit_type mismatch) returns 0.0, matching the report
    service's defensive behavior exactly (never double-counts, never
    crashes on unexpected data).
    """
    b = pricing.get("billing_units", {}).get(model)
    if not b or b.get("unit") != unit_type:
        return 0.0
    return (float(quantity) / b.get("per", 1)) * b.get("rate", 0.0)
