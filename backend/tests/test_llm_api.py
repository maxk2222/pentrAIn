"""LLM discovery/test endpoints — httpx is faked at the AsyncClient level."""
from __future__ import annotations

import json
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

import app.api.routes_admin as routes_admin
from app.main import app


class _FakeResp:
    def __init__(self, payload, status: int = 200):
        self._p, self.status_code = payload, status

    @property
    def text(self):
        return json.dumps(self._p)

    def json(self):
        return self._p


class _FakeClient:
    handler = None          # (method, url, headers, json) -> _FakeResp
    seen: ClassVar[list] = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        self.seen.append(("GET", url, headers, None))
        return _FakeClient.handler("GET", url, headers, None)

    async def post(self, url, headers=None, json=None):
        self.seen.append(("POST", url, headers, json))
        return _FakeClient.handler("POST", url, headers, json)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fake_llm(monkeypatch):
    _FakeClient.seen = []
    monkeypatch.setattr(routes_admin.httpx, "AsyncClient", _FakeClient)
    yield _FakeClient
    _FakeClient.handler = None


@pytest.fixture()
def llm_settings(client):
    client.patch("/api/settings", json={"updates": {
        "llm.base_url": "http://fake-llm:11434/v1",
        "llm.api_key": "secret-key",
    }})


def test_llm_models_sorted_and_auth(client, fake_llm, llm_settings):
    fake_llm.handler = lambda m, u, h, j: _FakeResp(
        {"data": [{"id": "b-model"}, {"id": "a-model"}, {"name": "no-id"}]})
    r = client.post("/api/llm/models", json={})
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True
    assert [m["id"] for m in out["models"]] == ["a-model", "b-model"]
    _method, url, headers, _ = fake_llm.seen[0]
    assert url == "http://fake-llm:11434/v1/models"
    assert headers["Authorization"] == "Bearer secret-key"


def test_llm_models_http_error(client, fake_llm, llm_settings):
    fake_llm.handler = lambda m, u, h, j: _FakeResp({"error": "unauthorized"}, 401)
    out = client.post("/api/llm/models", json={}).json()
    assert out["ok"] is False and "401" in out["error"] and out["models"] == []


def test_llm_models_draft_base_url_override(client, fake_llm, llm_settings):
    fake_llm.handler = lambda m, u, h, j: _FakeResp({"data": []})
    client.post("/api/llm/models", json={"base_url": "http://other:1234/v1/"})
    assert fake_llm.seen[0][1] == "http://other:1234/v1/models"  # trailing slash stripped


def test_llm_test_chat_ok(client, fake_llm, llm_settings):
    def handler(m, u, h, j):
        assert j["model"] == "m1"
        return _FakeResp({"choices": [{"message": {"content": "ok"}}]})
    fake_llm.handler = handler
    out = client.post("/api/llm/test",
                      json={"model": "m1", "kind": "chat"}).json()
    assert out["ok"] is True and out["sample"] == "ok" and out["latency_ms"] >= 0


def test_llm_test_vision_payload_and_404(client, fake_llm, llm_settings):
    seen_body = {}

    def handler(m, u, h, j):
        seen_body.update(j)
        return _FakeResp({"error": {"message": "model not found"}}, 404)

    fake_llm.handler = handler
    out = client.post("/api/llm/test",
                      json={"model": "vlm1", "kind": "vision"}).json()
    assert out["ok"] is False and "404" in out["error"]
    content = seen_body["messages"][0]["content"]
    assert any(p.get("type") == "image_url" for p in content)


def test_llm_test_redacted_key_falls_back(client, fake_llm, llm_settings):
    def handler(m, u, h, j):
        return _FakeResp({"choices": [{"message": {"content": "ok"}}]})
    fake_llm.handler = handler
    # "********" is what the UI echoes for an unchanged secret — stored key must be used
    client.post("/api/llm/test", json={"model": "m", "api_key": "********"})
    assert fake_llm.seen[0][2]["Authorization"] == "Bearer secret-key"


def test_llm_models_no_base_url(client, fake_llm):
    client.patch("/api/settings", json={"updates": {"llm.base_url": ""}})
    r = client.post("/api/llm/models", json={"base_url": ""})
    assert r.status_code == 422


def test_engine_resources_mock(client):
    r = client.get("/api/engine/resources")
    assert r.status_code == 200
    assert r.json()["ok"] is False and "mock" in r.json()["reason"]


def test_efforts_parses_supported_values(client, fake_llm, llm_settings):
    fake_llm.handler = lambda m, u, h, j: _FakeResp(
        {"error": {"message": "Invalid 'reasoning_effort' value: 'pentrain_probe'. "
                              "Supported values: none, minimal, low, medium, high, xhigh."}},
        400)
    out = client.post("/api/llm/reasoning-efforts", json={"model": "m1"}).json()
    assert out["ok"] is True and out["source"] == "endpoint"
    assert out["efforts"] == ["none", "minimal", "low", "medium", "high", "xhigh"]
    body = fake_llm.seen[0][3]
    assert body["reasoning_effort"] == "pentrain_probe" and body["model"] == "m1"


def test_efforts_fallback_on_success_or_vague_error(client, fake_llm, llm_settings):
    # endpoint ignores unknown effort entirely → union list marked fallback
    fake_llm.handler = lambda m, u, h, j: _FakeResp(
        {"choices": [{"message": {"content": ""}}]})
    out = client.post("/api/llm/reasoning-efforts", json={"model": "m1"}).json()
    assert out["ok"] is True and out["source"] == "fallback"
    assert "high" in out["efforts"]

    # error without a parseable list → same fallback
    fake_llm.handler = lambda m, u, h, j: _FakeResp({"error": "bad request"}, 400)
    out = client.post("/api/llm/reasoning-efforts", json={"model": "m1"}).json()
    assert out["ok"] is True and out["source"] == "fallback"


def test_efforts_uses_saved_model_and_key(client, fake_llm, llm_settings):
    client.patch("/api/settings", json={"updates": {"llm.model": "saved-model"}})
    fake_llm.handler = lambda m, u, h, j: _FakeResp({"error": "bad"}, 400)
    client.post("/api/llm/reasoning-efforts", json={"api_key": "********"})
    _method, _url, headers, body = fake_llm.seen[0]
    assert body["model"] == "saved-model"
    assert headers["Authorization"] == "Bearer secret-key"


def test_efforts_no_model(client, fake_llm, llm_settings):
    client.patch("/api/settings", json={"updates": {"llm.model": ""}})
    out = client.post("/api/llm/reasoning-efforts", json={}).json()
    assert out["ok"] is False and "model" in out["error"]


def test_engine_metrics_mock(client):
    out = client.get("/api/engine/metrics?timeframe=bogus").json()
    assert out["ok"] is False and "mock" in out["reason"]


def test_llm_usage_roundtrip(client):
    from app.config import get_config
    tok = get_config().coach_service_token
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/api/coach/llm-usage", headers=h, json={
        "session_id": None, "model": "m1", "kind": "chat",
        "prompt_tokens": 10, "completion_tokens": 5,
        "total_tokens": 15, "latency_ms": 120})
    assert r.status_code == 204
    out = client.get("/api/llm/usage?days=7").json()
    assert isinstance(out["days"], list)
    assert any(d["tokens"] >= 15 for d in out["days"])
    # wrong token → service auth rejects
    r = client.post("/api/coach/llm-usage",
                    headers={"Authorization": "Bearer wrong"}, json={})
    assert r.status_code == 401
