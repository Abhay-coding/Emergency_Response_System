from app.core.constants import DEFAULT_ALLOWED_HEADERS


def test_alert_preflight_policy_allows_idempotency_key():
    # The browser sends this custom header before a one-tap alert POST.  It
    # must be present in the shared policy used by FastAPI's CORS middleware.
    assert "Idempotency-Key" in DEFAULT_ALLOWED_HEADERS
