from x_scrap.adapters.base import AuthRequired, RateLimited, TransientUpstreamError, UpstreamChanged
from x_scrap.adapters.twscrape_adapter import _classify, _validate_cookie


def test_cookie_validation_requires_both_browser_cookie_fields():
    _validate_cookie("auth_token=xxx; ct0=yyy")
    for value in ("auth_token=xxx", "ct0=yyy", "auth_token=xxx\nct0=yyy"):
        try:
            _validate_cookie(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid cookie accepted: {value!r}")


def test_upstream_errors_are_classified_conservatively():
    assert isinstance(_classify(RuntimeError("429 rate limit")), RateLimited)
    assert isinstance(_classify(RuntimeError("login challenge")), AuthRequired)
    assert isinstance(_classify(RuntimeError("GraphQL operation missing 404")), UpstreamChanged)
    assert isinstance(_classify(RuntimeError("503 temporary connection failure")), TransientUpstreamError)
    assert isinstance(_classify(RuntimeError("unexpected response")), UpstreamChanged)
