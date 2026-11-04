"""web_search / web_fetch — parsers, SSRF guard, caching, dispatch gating.

The HTTP client and DNS resolver are stubbed throughout: these tests must
pass without any network egress.
"""
from __future__ import annotations

import ipaddress  # noqa: F401
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach import websearch
from coach.tools import WORKER_TOOL_NAMES, tools_for_level

# ---------- stubs ----------

class _Resp:
    def __init__(self, text="", status=200, ctype="text/html",
                 location=None, url="https://x.test/"):
        self.text = text
        self.status_code = status
        self.headers = {"content-type": ctype}
        if location:
            self.headers["location"] = location
        self.url = url
        self.content = text.encode()
        self.is_redirect = status in (301, 302, 303, 307, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("e", request=None, response=None)

    def json(self):
        import json
        return json.loads(self.text)


class _FakeHTTP:
    """Routes (method, url-prefix) → queued responses."""

    def __init__(self):
        self.routes: dict[tuple[str, str], list[_Resp]] = {}
        self.calls: list[tuple[str, str]] = []

    def add(self, method: str, prefix: str, *resps: _Resp) -> None:
        self.routes[(method, prefix)] = list(resps)

    def _take(self, method: str, url: str) -> _Resp:
        self.calls.append((method, url))
        for (m, p), q in self.routes.items():
            if m == method and url.startswith(p) and q:
                return q.pop(0)
        raise AssertionError(f"unstubbed {method} {url}")

    async def post(self, url, data=None, headers=None):
        return self._take("POST", url)

    async def get(self, url, headers=None):
        return self._take("GET", url)


def _ws(client: _FakeHTTP) -> websearch.WebSearch:
    return websearch.WebSearch(client=client)


def _public_dns(host: str, port=None):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


# ---------- fixtures ----------

DDG_HTML = """
<html><body>
<div class="result"><a class="result__a" href="https://nvd.nist.gov/vuln/detail/CVE-2024-4577">NVD - CVE-2024-4577</a>
<a class="result__snippet">PHP CGI argument injection on Windows RCE.</a></div>
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fwatchtowrlabs%2FCVE-2024-4577&amp;rut=abc">watchtowr PoC</a>
<div class="result__snippet">PoC writeup.</div></div>
</body></html>
"""

DDG_LITE = """
<html><body><table>
<tr><td><a class="result-link" href="https://sentinelone.com/vuln/cve-2024-4577">SentinelOne CVE-2024-4577</a></td></tr>
<tr><td class="result-snippet">Vendor advisory for the PHP-CGI bug.</td></tr>
</table></body></html>
"""

CHALLENGE = '<html><body><div class="anomaly-modal">prove you are human</div></body></html>'


# ---------- unit: parsers ----------

def test_parse_ddg_html_results_and_uddg():
    res = websearch._parse_ddg_html(DDG_HTML)
    assert len(res) == 2
    assert res[0]["title"] == "NVD - CVE-2024-4577"
    assert res[0]["url"] == "https://nvd.nist.gov/vuln/detail/CVE-2024-4577"
    assert "PHP CGI" in res[0]["snippet"]
    # redirect-wrapped hrefs decode to the real target
    assert res[1]["url"] == "https://github.com/watchtowrlabs/CVE-2024-4577"


def test_parse_ddg_lite_results():
    res = websearch._parse_ddg_lite(DDG_LITE)
    assert len(res) == 1
    assert res[0]["url"].startswith("https://sentinelone.com/")
    assert "advisory" in res[0]["snippet"]


def test_challenge_detection():
    assert websearch._is_challenged(CHALLENGE)
    assert not websearch._is_challenged(DDG_HTML)


def test_decode_ddg_url_scheme_relative():
    assert websearch._decode_ddg_url("//example.com/x") == "https://example.com/x"


# ---------- unit: SSRF primitives ----------

@pytest.mark.parametrize("host", ["127.0.0.1", "10.1.10.32", "192.168.3.95",
                                  "172.16.0.5", "169.254.169.254", "::1",
                                  "2130706433"])
def test_host_literal_flags_private(host):
    lit = websearch._host_literal(host)
    assert lit is not None and websearch._blocked_ip(lit)


def test_host_literal_public_passes():
    lit = websearch._host_literal("93.184.216.34")
    assert lit is not None and not websearch._blocked_ip(lit)
    assert websearch._host_literal("example.com") is None


# ---------- search ----------

async def test_search_formats_results(monkeypatch):
    monkeypatch.setattr(websearch, "_SEARCH_DEBOUNCE_S", 0)
    c = _FakeHTTP()
    c.add("POST", websearch._DDG_HTML, _Resp(DDG_HTML))
    out = await _ws(c).search("CVE-2024-4577")
    assert "2 results" in out
    assert "nvd.nist.gov" in out and "github.com/watchtowrlabs" in out


async def test_search_falls_back_after_challenge(monkeypatch):
    monkeypatch.setattr(websearch, "_SEARCH_DEBOUNCE_S", 0)
    c = _FakeHTTP()
    c.add("POST", websearch._DDG_HTML, _Resp(CHALLENGE))
    c.add("POST", websearch._DDG_LITE, _Resp(DDG_LITE))
    out = await _ws(c).search("php cgi rce")
    assert "sentinelone.com" in out
    assert ("POST", websearch._DDG_LITE) in c.calls


async def test_search_all_engines_down(monkeypatch):
    monkeypatch.setattr(websearch, "_SEARCH_DEBOUNCE_S", 0)
    c = _FakeHTTP()
    c.add("POST", websearch._DDG_HTML, _Resp(CHALLENGE))
    c.add("POST", websearch._DDG_LITE, _Resp("", status=503))
    c.add("GET", "https://api.marginalia.nu", _Resp("{}", status=500))
    out = await _ws(c).search("x")
    assert out.startswith("error: web search failed")


async def test_search_cache_prefix(monkeypatch):
    monkeypatch.setattr(websearch, "_SEARCH_DEBOUNCE_S", 0)
    c = _FakeHTTP()
    c.add("POST", websearch._DDG_HTML, _Resp(DDG_HTML))
    ws = _ws(c)
    await ws.search("q")
    out = await ws.search("q")
    assert out.startswith("CACHED:")
    assert len(c.calls) == 1  # no second upstream hit


async def test_marginalia_json_shape(monkeypatch):
    monkeypatch.setattr(websearch, "_SEARCH_DEBOUNCE_S", 0)
    c = _FakeHTTP()
    c.add("POST", websearch._DDG_HTML, _Resp(CHALLENGE))
    c.add("POST", websearch._DDG_LITE, _Resp(CHALLENGE))
    c.add("GET", "https://api.marginalia.nu", _Resp(
        '{"results":[{"url":"https://hacktricks.xyz/x","title":"HT",'
        '"description":"d"}]}'))
    out = await _ws(c).search("kerberos delegation")
    assert "hacktricks.xyz" in out


# ---------- fetch ----------

async def test_fetch_denies_private_ip(monkeypatch):
    monkeypatch.setattr(websearch.socket, "getaddrinfo",
                        lambda h, p=None: [(2, 1, 6, "", ("10.1.10.32", 0))])
    c = _FakeHTTP()
    out = await _ws(c).fetch("http://app01.lab/admin")
    assert "private" in out and "denied" in out
    assert c.calls == []  # request never left


async def test_fetch_denies_literal_ip():
    for u in ("http://127.0.0.1/x", "http://2130706433/x",
              "http://169.254.169.254/latest/meta-data"):
        out = await _ws(_FakeHTTP()).fetch(u)
        assert "denied" in out, u


async def test_fetch_denies_redirect_into_lab(monkeypatch):
    monkeypatch.setattr(websearch.socket, "getaddrinfo", _public_dns)
    c = _FakeHTTP()
    # first hop resolves public, second hop 10.x — the per-hop recheck fires
    def dns(host, port=None):
        ip = "93.184.216.34" if "evil" in host else "10.1.10.32"
        return [(2, 1, 6, "", (ip, 0))]
    monkeypatch.setattr(websearch.socket, "getaddrinfo", dns)
    c.add("GET", "https://evil.example/", _Resp(
        status=302, location="http://labhost/loot"))
    out = await _ws(c).fetch("https://evil.example/r")
    assert "denied" in out and "10.1.10.32" in out


async def test_fetch_extracts_text_and_url(monkeypatch):
    monkeypatch.setattr(websearch.socket, "getaddrinfo", _public_dns)
    c = _FakeHTTP()
    c.add("GET", "https://example.com/", _Resp(
        "<html><head><title>t</title></head><body>"
        "<nav>junk</nav><article><p>main content here</p></article>"
        "</body></html>", url="https://example.com/a"))
    out = await _ws(c).fetch("https://example.com/a")
    assert out.startswith("URL: https://example.com/a")
    assert "main content here" in out


async def test_fetch_binary_content_type(monkeypatch):
    monkeypatch.setattr(websearch.socket, "getaddrinfo", _public_dns)
    c = _FakeHTTP()
    c.add("GET", "https://example.com/f", _Resp("PK\x03\x04", ctype="application/zip"))
    out = await _ws(c).fetch("https://example.com/f.zip")
    assert "binary/unsupported" in out


async def test_fetch_truncates_and_caches(monkeypatch):
    monkeypatch.setattr(websearch.socket, "getaddrinfo", _public_dns)
    c = _FakeHTTP()
    c.add("GET", "https://example.com/", _Resp(
        "<html><body><article>" + "x" * 9000 + "</article></body></html>"))
    ws = _ws(c)
    out = await ws.fetch("https://example.com/big", max_chars=500)
    assert "truncated" in out
    assert (await ws.fetch("https://example.com/big")).startswith("CACHED:")


# ---------- dispatch gating ----------

from tests.test_loop_reactions import FakeClient, _coach


def _ctx_with_net(c: FakeClient, on: bool) -> None:
    c.ctx["session"]["kali_internet"] = on
    c.ctx["session"]["autonomy_level"] = 4


async def test_dispatch_denies_web_when_offline():
    coach, c = _coach()
    coach.state.autonomy_level = 4
    _ctx_with_net(c, False)
    for t in ("web_search", "web_fetch"):
        _, res = await coach._dispatch_inner(
            {"type": t, "query": "x", "url": "https://x.test"})
        assert res.startswith("denied: web — offline lab"), res


async def test_dispatch_calls_websearch_when_online():
    coach, c = _coach()
    coach.state.autonomy_level = 4
    _ctx_with_net(c, True)

    class _Stub:
        async def search(self, q, n):
            return f"results for {q}"

        async def fetch(self, u):
            return f"URL: {u}\n\nbody"

    coach._web = _Stub()
    _, res = await coach._dispatch_inner({"type": "web_search", "query": "cve x"})
    assert "results for cve x" in res
    _, res = await coach._dispatch_inner(
        {"type": "web_fetch", "url": "https://a.b/d"})
    assert "URL: https://a.b/d" in res


def test_level_and_worker_gating():
    names3 = {t["function"]["name"] for t in tools_for_level(3)}
    names1 = {t["function"]["name"] for t in tools_for_level(1)}
    assert {"web_search", "web_fetch"} <= names3
    assert {"web_search", "web_fetch"}.isdisjoint(names1)
    assert {"web_search", "web_fetch"} <= WORKER_TOOL_NAMES
