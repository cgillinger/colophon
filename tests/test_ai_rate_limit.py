# Colophon – tests for how a 429 from the AI provider is read
"""One status code, two very different situations.

HTTP 429 covers both "you are sending requests faster than the tier
allows" — wait and it works again — and "this account's quota is gone",
where waiting achieves nothing. Telling the user to try again later is
actively wrong in the second case, so `_rate_limit_error` reads what the
provider revealed: a Retry-After header means the first kind, and the
response body names the second.

The error code stays "rate_limit" in every case. Callers that only branch
on the code keep working; the extra fields are what let a surface say
something more useful than "it failed".
"""
from unittest.mock import MagicMock, patch

from app.services import ai_metadata
from app.services.ai_metadata import _rate_limit_error


def _resp(headers=None, body=""):
    resp = MagicMock()
    resp.headers = headers or {}
    resp.text = body
    return resp


def test_retry_after_is_carried_as_seconds():
    result = _rate_limit_error(_resp(headers={"Retry-After": "90"}))
    assert result == {"ok": False, "error": "rate_limit", "retry_after": 90,
                      "quota": False, "allowance_zero": False}


def test_non_numeric_retry_after_is_ignored():
    """Retry-After may be an HTTP date. We do not parse those — reporting
    no number is honest; reporting a wrong one is not."""
    result = _rate_limit_error(_resp(headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))
    assert result["retry_after"] is None
    assert result["quota"] is False


def test_body_naming_the_quota_sets_the_quota_flag():
    result = _rate_limit_error(
        _resp(body='{"message": "You exceeded your current quota, check your plan"}')
    )
    assert result["quota"] is True
    assert result["retry_after"] is None


def test_billing_wording_also_counts_as_quota():
    result = _rate_limit_error(_resp(body='{"error": "insufficient credit on this account"}'))
    assert result["quota"] is True


def test_plain_429_says_neither():
    """No header, nothing in the body: we know only that it was a 429, and
    the UI must say that rather than invent a reason."""
    result = _rate_limit_error(_resp(body='{"message": "Requests rate limit exceeded"}'))
    assert result["retry_after"] is None
    assert result["quota"] is False


def test_unreadable_body_does_not_raise():
    resp = MagicMock()
    resp.headers = {}
    type(resp).text = property(lambda self: (_ for _ in ()).throw(ValueError("no body")))

    result = _rate_limit_error(resp)
    assert result["error"] == "rate_limit"
    assert result["quota"] is False


def test_zero_requests_per_minute_is_an_account_problem():
    """The real symptom on this library's own account: a valid key, no usage
    to speak of, and a ceiling of zero requests per minute. That is a
    workspace without an active plan, not a busy service — and only the
    header says so, the body just reads "Rate limit exceeded"."""
    result = _rate_limit_error(_resp(
        headers={"x-ratelimit-limit-req-minute": "0",
                 "x-ratelimit-remaining-req-minute": "0"},
        body='{"message": "Rate limit exceeded", "type": "rate_limited"}',
    ))
    assert result["allowance_zero"] is True
    assert result["quota"] is False
    assert result["retry_after"] is None


def test_a_normal_ceiling_is_not_an_account_problem():
    result = _rate_limit_error(_resp(headers={"x-ratelimit-limit-req-minute": "60"}))
    assert result["allowance_zero"] is False


# --- the callers ----------------------------------------------------------

def test_connection_test_reports_the_quota(monkeypatch):
    """test_ai_connection is the surface a user reaches for first when the
    AI stops answering, so the detail has to survive the call, not just the
    helper."""
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    resp.text = '{"message": "quota exceeded"}'

    monkeypatch.setattr(ai_metadata, "get_setting",
                        lambda key, default=None: {"AI_API_KEY": "k"}.get(key, ""))
    with patch.object(ai_metadata.requests, "post", return_value=resp):
        result = ai_metadata.test_ai_connection()

    assert result["error"] == "rate_limit"
    assert result["quota"] is True


def test_series_proposal_carries_the_detail_through(monkeypatch):
    """The newest AI call must not drop the fields on the floor — the
    series modal is one of the surfaces that used to say only "it failed"."""
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": "30"}
    resp.text = ""

    monkeypatch.setattr(ai_metadata, "ai_is_configured", lambda: True)
    monkeypatch.setattr(ai_metadata, "get_setting",
                        lambda key, default=None: {"AI_API_KEY": "k"}.get(key, ""))
    books = [{"id": 1, "title": "A", "author": "B", "series": "",
              "series_index": "", "published_date": "", "file_name": ""}]
    with patch.object(ai_metadata.requests, "post", return_value=resp):
        result = ai_metadata.propose_series_order(books)

    assert result["error"] == "rate_limit"
    assert result["retry_after"] == 30
