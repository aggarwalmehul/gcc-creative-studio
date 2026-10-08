"""Token usage logging to BigQuery, with per-user context via ContextVar."""
import datetime, logging, contextvars
log = logging.getLogger("token_logger")
try:
    from google.cloud import bigquery
    _bq = bigquery.Client(project="ltm-craftstudio-poc")
    log.info("TOKENLOG: bigquery client initialized")
except Exception as e:
    _bq = None
    log.warning("TOKENLOG: bq init failed: %s", e)

_TABLE = "ltm-craftstudio-poc.token_usage.usage"
# FEATURE_PORT_BILLING_UNITS_V1: raw billing quantities (seconds/images/chars);
# priced downstream in genai-token-report (backend never computes cost).
_BILLING_TABLE = "ltm-craftstudio-poc.token_usage.billing_units"
current_user_email = contextvars.ContextVar("current_user_email", default="unknown")

# TOKEN_LOGGING_AUDIT_FIX_V1: the google-genai SDK exposes token usage in TWO
# incompatible shapes depending on which API family a response came from:
#   - client.models.generate_content(...) (Gemini text/image/TTS calls)
#     -> resp.usage_metadata.{prompt_token_count, candidates_token_count,
#        total_token_count}
#   - client.interactions.create(...) (Omni video, Lyria 3 Pro/Clip -- the
#     newer "Interactions API" shared by these features)
#     -> resp.usage.{total_input_tokens, total_output_tokens, total_tokens}
# Without this, calls made via interactions.create() would silently be
# skipped ("no usage_metadata on resp") even though they DO carry usage
# data, just under a different attribute name and field names.
def _normalize_usage(resp):
    """Returns (prompt_tokens, candidates_tokens, total_tokens) from
    whichever of the two known usage shapes `resp` actually has, or
    None if neither is present."""
    u = getattr(resp, "usage_metadata", None)
    if u is not None:
        return (
            int(getattr(u, "prompt_token_count", 0) or 0),
            int(getattr(u, "candidates_token_count", 0) or 0),
            int(getattr(u, "total_token_count", 0) or 0),
        )
    u = getattr(resp, "usage", None)
    if u is not None:
        return (
            int(getattr(u, "total_input_tokens", 0) or 0),
            int(getattr(u, "total_output_tokens", 0) or 0),
            int(getattr(u, "total_tokens", 0) or 0),
        )
    return None


def log_tokens(platform: str, model: str, resp):
    if _bq is None:
        log.warning("TOKENLOG: skip — no bq client"); return
    usage = _normalize_usage(resp)
    if usage is None:
        log.warning("TOKENLOG: skip — no usage_metadata/usage on resp (type=%s)", type(resp).__name__); return
    tokens_in, tokens_out, total = usage
    row = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform,
        "user_email": current_user_email.get() or "unknown",
        "model": str(model),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total": total,
    }
    try:
        errors = _bq.insert_rows_json(_TABLE, [row])
        if errors:
            log.warning("TOKENLOG: insert errors: %s", errors)   # ← now surfaced!
        else:
            log.info("TOKENLOG: inserted %s tokens for %s", row["total"], model)
    except Exception as e:
        log.warning("TOKENLOG: insert exception: %s", e)


# FEATURE_PORT_BILLING_UNITS_V1: parallel to log_tokens(), but for the
# non-LLM media models that bill per-second / per-image / per-character
# rather than per-token. Logs the RAW quantity + unit only; the report
# service applies the per-unit rate. Never raises.
def log_billing_units(platform: str, model: str, unit_type: str, quantity):
    if _bq is None:
        log.warning("BILLINGUNITS: skip — no bq client"); return
    try:
        q = float(quantity or 0)
    except Exception:
        log.warning("BILLINGUNITS: skip — non-numeric quantity %r", quantity); return
    if q <= 0:
        log.info("BILLINGUNITS: skip — zero quantity for %s", model); return
    row = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform,
        "user_email": current_user_email.get() or "unknown",
        "model": str(model),
        "unit_type": str(unit_type),
        "quantity": q,
    }
    try:
        errors = _bq.insert_rows_json(_BILLING_TABLE, [row])
        if errors:
            log.warning("BILLINGUNITS: insert errors: %s", errors)
        else:
            log.info("BILLINGUNITS: inserted %.3f %s for %s", q, unit_type, model)
    except Exception as e:
        log.warning("BILLINGUNITS: insert exception: %s", e)
