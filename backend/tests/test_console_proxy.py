"""Console proxy — the upstream vncwebsocket handshake must carry the PVE API
token or pveproxy answers 401 and the browser just shows 'disconnected'."""
from __future__ import annotations

import asyncio

import app.services.console as console_svc
from app.models.domain import Session, SessionState
from app.ranges.pve import PveClient, PveCreds


def _creds() -> PveCreds:
    return PveCreds(base_url="https://pve.local:8006", node="pve",
                    token_id="root@pam!pentrain", token_secret="s3cret",
                    verify_tls=False)


def test_auth_headers_carry_api_token():
    h = PveClient(_creds()).auth_headers()
    assert h["Authorization"] == "PVEAPIToken=root@pam!pentrain=s3cret"


def test_vnc_websocket_url_shape():
    url = PveClient(_creds()).vnc_websocket_url(103, "5900", "tick&et=")
    assert url.startswith("wss://pve.local:8006/api2/json/nodes/pve/qemu/103/vncwebsocket?")
    assert "port=5900" in url and "vncticket=tick%26et%3D" in url


class _FakeUpstream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def send(self, data):
        pass


async def test_proxy_passes_auth_headers(monkeypatch, db):
    db.add(Session(quest_id="q1", state=SessionState.ACTIVE.value, kali_vmid=103))
    await db.commit()
    sess_id = 1

    class _Pve:
        def ssl_context(self):
            return None

        def auth_headers(self):
            return {"Authorization": "PVEAPIToken=u!t=s"}

        def vnc_websocket_url(self, vmid, port, ticket):
            return "wss://pve.local/x"

        async def vncproxy(self, vmid):
            return {"port": "5900", "ticket": "t"}

    class _Engine:
        mode = "direct"
        pve = _Pve()

    async def _fake_engine(_db):
        return _Engine()

    calls: dict = {}

    def _connect(url, **kw):
        calls["url"] = url
        calls.update(kw)
        return _FakeUpstream()

    async def _done():
        await asyncio.sleep(0)

    class _Ws:
        accepted = False

        async def accept(self):
            self.accepted = True

        async def receive(self):
            await asyncio.sleep(3600)  # client stays silent; gets cancelled

        async def send_bytes(self, b):
            pass

        async def send_text(self, t):
            pass

        async def close(self, code=1000):
            pass

    monkeypatch.setattr(console_svc, "get_engine", _fake_engine)
    monkeypatch.setattr(console_svc.websockets, "connect", _connect)

    async def _run():
        await console_svc.proxy_console(db, _Ws(), sess_id)

    await asyncio.wait_for(_run(), timeout=5)
    assert calls["additional_headers"] == {"Authorization": "PVEAPIToken=u!t=s"}
    assert calls["subprotocols"] == ["binary"]
