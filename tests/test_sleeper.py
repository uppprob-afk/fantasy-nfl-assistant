import httpx
import pytest

from nfl_assistant import sleeper
from nfl_assistant.sleeper import SleeperClient


def client_with(responses, monkeypatch):
    """A client whose HTTP calls return the given status codes in order (then 200 + {"ok": 1})."""
    codes = list(responses)

    def handler(request):
        code = codes.pop(0) if codes else 200
        return httpx.Response(code, json={"ok": 1} if code == 200 else {}, request=request)

    monkeypatch.setattr(sleeper.time, "sleep", lambda s: None)
    c = SleeperClient("https://api.example", delay_seconds=0, max_retries=4)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_retries_cloudflare_522_then_succeeds(monkeypatch):
    c = client_with([522, 522, 500], monkeypatch)
    assert c.get("league/1") == {"ok": 1} and c.calls == 4


def test_gives_up_after_max_retries(monkeypatch):
    c = client_with([503] * 10, monkeypatch)
    with pytest.raises(RuntimeError, match="after 5 tries"):
        c.get("league/1")


def test_client_errors_are_not_retried(monkeypatch):
    c = client_with([404], monkeypatch)
    with pytest.raises(httpx.HTTPStatusError):
        c.get("league/1")
    assert c.calls == 1
