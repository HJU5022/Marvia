"""카카오 클라이언트(clients/kakao.py) 단위 테스트.

가짜 서버(httpx.MockTransport)와 가짜 환경변수(monkeypatch)만 쓴다. 진짜 카카오 호출도, 진짜 .env 읽기도 없다.
값은 모두 테스트용 가공값이다. 출처: 카카오 로그인·카카오톡 메시지 REST API 문서.
"""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.app.clients import kakao, retry
from backend.app.clients.kakao import KakaoError, Tokens

KEY, SECRET, REDIRECT = "test-rest-key", "test-client-secret", "http://localhost:8000/cb?x=1"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """모든 테스트에 가짜 키를 깔아 둔다. 재시도 대기도 0으로 줄여 테스트가 느려지지 않게 한다."""
    monkeypatch.setenv("KAKAO_REST_API_KEY", f"  {KEY}  ")  # 앞뒤 공백은 잘려야 한다
    monkeypatch.setenv("KAKAO_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("KAKAO_REDIRECT_URI", REDIRECT)
    monkeypatch.setattr(retry, "BACKOFF_SEC", 0)


def _transport(status: int = 200, body: dict | str | None = None, calls: list | None = None):
    """항상 같은 응답을 주는 가짜 서버. 받은 요청은 calls에 쌓는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(status, json=body if body is not None else {})

    return httpx.MockTransport(handler)


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


# ── config ──

def test_config_strips_values():
    assert kakao.config() == (KEY, SECRET, REDIRECT)


@pytest.mark.parametrize("name", ["KAKAO_REST_API_KEY", "KAKAO_CLIENT_SECRET"])
def test_config_missing_key_or_secret(monkeypatch, name):
    monkeypatch.setenv(name, "   ")
    with pytest.raises(KakaoError) as e:
        kakao.config()
    assert e.value.kind == "not_configured"


def test_config_empty_redirect_uses_default(monkeypatch):
    monkeypatch.setenv("KAKAO_REDIRECT_URI", "")
    assert kakao.config()[2] == kakao.DEFAULT_REDIRECT_URI
    assert kakao.DEFAULT_REDIRECT_URI == "http://localhost:3000/settings/kakao"  # 백엔드가 아니라 우리 화면


# ── authorize_url ──

def test_authorize_url_has_params_and_is_encoded():
    url = kakao.authorize_url("st ate&1")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://kauth.kakao.com/oauth/authorize"
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q == {"response_type": "code", "client_id": KEY, "redirect_uri": REDIRECT,
                 "scope": "talk_message", "state": "st ate&1"}
    assert "st%20ate%261" in url or "st+ate%261" in url  # 날것으로 들어가지 않는다
    assert "http%3A%2F%2Flocalhost" in url
    assert SECRET not in url


# ── exchange_code ──

TOKEN_BODY = {"access_token": "AT", "expires_in": 43199, "refresh_token": "RT",
              "refresh_token_expires_in": 5184000, "scope": "talk_message"}


def test_exchange_code_sends_form_and_parses_tokens():
    calls = []
    tokens = kakao.exchange_code("the-code", transport=_transport(200, TOKEN_BODY, calls))

    assert tokens == Tokens("AT", 43199, "RT", 5184000, "talk_message")
    assert len(calls) == 1
    req = calls[0]
    assert req.method == "POST" and str(req.url) == "https://kauth.kakao.com/oauth/token"
    assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert _form(req) == {"grant_type": "authorization_code", "client_id": KEY, "redirect_uri": REDIRECT,
                          "code": "the-code", "client_secret": SECRET}


def test_exchange_code_does_not_retry_on_500():
    calls = []
    with pytest.raises(KakaoError) as e:
        kakao.exchange_code("c", transport=_transport(500, {}, calls))
    assert (e.value.kind, e.value.code) == ("failed", 500)
    assert len(calls) == 1


def test_exchange_code_bad_request_is_failed():
    with pytest.raises(KakaoError) as e:
        kakao.exchange_code("c", transport=_transport(400, {"error": "invalid_grant", "error_code": "KOE320"}))
    assert (e.value.kind, e.value.code) == ("failed", 400)


def test_exchange_code_not_configured(monkeypatch):
    monkeypatch.setenv("KAKAO_CLIENT_SECRET", "")
    with pytest.raises(KakaoError) as e:
        kakao.exchange_code("c", transport=_transport(200, TOKEN_BODY))
    assert e.value.kind == "not_configured"


def test_network_error_is_failed():
    def boom(request):
        raise httpx.ConnectError("secret detail", request=request)

    with pytest.raises(KakaoError) as e:
        kakao.exchange_code("c", transport=httpx.MockTransport(boom))
    assert e.value.kind == "failed" and "secret detail" not in str(e.value)


# ── refresh ──

def test_refresh_without_new_refresh_token_gives_none():
    calls = []
    body = {"access_token": "AT2", "expires_in": 43199, "scope": "talk_message"}
    tokens = kakao.refresh("old-rt", transport=_transport(200, body, calls))

    assert tokens == Tokens("AT2", 43199, None, None, "talk_message")
    assert _form(calls[0]) == {"grant_type": "refresh_token", "client_id": KEY, "refresh_token": "old-rt",
                               "client_secret": SECRET}


def test_refresh_with_new_refresh_token():
    tokens = kakao.refresh("old-rt", transport=_transport(200, TOKEN_BODY))
    assert (tokens.refresh_token, tokens.refresh_expires_in) == ("RT", 5184000)


def test_refresh_invalid_grant_is_unauthorized():
    with pytest.raises(KakaoError) as e:
        kakao.refresh("dead", transport=_transport(400, {"error": "invalid_grant", "error_code": "KOE320"}))
    assert e.value.kind == "unauthorized"


def test_refresh_other_4xx_is_failed():
    with pytest.raises(KakaoError) as e:
        kakao.refresh("rt", transport=_transport(401, {"error": "invalid_client", "error_code": "KOE010"}))
    assert (e.value.kind, e.value.code) == ("failed", 401)


def test_refresh_retries_on_500():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, json={})
        return httpx.Response(200, json=TOKEN_BODY)

    assert kakao.refresh("rt", transport=httpx.MockTransport(handler)).access_token == "AT"
    assert len(calls) == 2


# ── send_memo ──

def test_send_memo_sends_bearer_and_template():
    calls = []
    kakao.send_memo("AT", "화물 알림", "https://marvia.example/x", transport=_transport(200, {"result_code": 0}, calls))

    req = calls[0]
    assert req.method == "POST" and str(req.url) == "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    assert req.headers["authorization"] == "Bearer AT"
    template = json.loads(_form(req)["template_object"])
    assert template == {"object_type": "text", "text": "화물 알림",
                        "link": {"web_url": "https://marvia.example/x", "mobile_web_url": "https://marvia.example/x"},
                        "button_title": "Marvia 열기"}


def test_send_memo_custom_button_title():
    calls = []
    kakao.send_memo("AT", "t", "https://x.example", "열기", transport=_transport(200, {"result_code": 0}, calls))
    assert json.loads(_form(calls[0])["template_object"])["button_title"] == "열기"


def test_send_memo_does_not_retry_on_500():
    calls = []
    with pytest.raises(KakaoError) as e:
        kakao.send_memo("AT", "t", "https://x.example", transport=_transport(500, {}, calls))
    assert (e.value.kind, e.value.code) == ("failed", 500)
    assert len(calls) == 1  # 재시도하면 같은 알림이 두 번 갈 수 있다


def test_send_memo_401_is_unauthorized():
    with pytest.raises(KakaoError) as e:
        kakao.send_memo("AT", "t", "https://x.example",
                        transport=_transport(401, {"msg": "this access token does not exist", "code": -401}))
    assert (e.value.kind, e.value.code) == ("unauthorized", -401)


@pytest.mark.parametrize("code", [-402, -3])
def test_send_memo_403_is_no_consent(code):
    with pytest.raises(KakaoError) as e:
        kakao.send_memo("AT", "t", "https://x.example", transport=_transport(403, {"msg": "no", "code": code}))
    assert (e.value.kind, e.value.code) == ("no_consent", code)


def test_send_memo_other_error_is_failed():
    with pytest.raises(KakaoError) as e:
        kakao.send_memo("AT", "t", "https://x.example", transport=_transport(400, {"msg": "bad", "code": -2}))
    assert (e.value.kind, e.value.code) == ("failed", 400)


# ── unlink ──

def test_unlink_sends_bearer():
    calls = []
    kakao.unlink("AT", transport=_transport(200, {"id": 1}, calls))
    assert str(calls[0].url) == "https://kapi.kakao.com/v1/user/unlink"
    assert calls[0].headers["authorization"] == "Bearer AT"


def test_unlink_401_is_success():
    kakao.unlink("AT", transport=_transport(401, {"msg": "dead", "code": -401}))  # 예외 없이 끝나야 한다


def test_unlink_other_error_is_failed():
    with pytest.raises(KakaoError) as e:
        kakao.unlink("AT", transport=_transport(400, {"msg": "bad", "code": -2}))
    assert (e.value.kind, e.value.code) == ("failed", 400)


def test_unlink_retries_on_500():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500 if len(calls) == 1 else 200, json={})

    kakao.unlink("AT", transport=httpx.MockTransport(handler))
    assert len(calls) == 2


# ── 비밀 값이 새지 않는지 ──

def test_secrets_not_in_error_or_repr():
    with pytest.raises(KakaoError) as e:
        kakao.exchange_code("the-code", transport=_transport(400, {"error": "invalid_grant"}))
    text = f"{e.value!s} {e.value!r}"
    for secret in (SECRET, KEY, "the-code"):
        assert secret not in text
    assert "AT" not in repr(Tokens("AT-secret", 1, "RT-secret", 1, None))
    assert "RT-secret" not in repr(Tokens("AT-secret", 1, "RT-secret", 1, None))
