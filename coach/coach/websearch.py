"""Key-free web research for the coach agent — search + fetch.

Two tools ride this module (web_search / web_fetch); dispatch gates them on
the session's `kali_internet` flag, so this file only worries about getting
good results back, not about whether the call is allowed.

Search chain — no API keys anywhere:
  1. html.duckduckgo.com/html/  POST form — cleanest markup, organic results
  2. lite.duckduckgo.com/lite/  POST form — different fingerprint surface
  3. api.marginalia.nu public key — indie index, tolerant JSON parse

DuckDuckGo rate-limits datacenter IPs behind an `anomaly-modal` challenge;
a residential egress usually passes, but every engine failure must degrade
honestly ("unavailable") instead of returning empty-looking garbage.

Fetch is an SSRF surface by definition: any URL the model emits gets DNS-
resolved and rejected when it lands on private/loopback/link-local/reserved
space — which also covers every lab CIDR — and the same check runs on each
redirect hop. Body extraction goes through trafilatura (main-content text)
with a regex-strip fallback so a partial lxml break still returns something.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
import time
import urllib.parse

import httpx

try:
    import trafilatura
except ImportError:  # lxml chain missing — regex fallback still works
    trafilatura = None

_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
       "Gecko/20100101 Firefox/128.0")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # fetch-metadata headers matter: DDG's bot filter weighs Sec-Fetch-Mode
    # heavily — a bare httpx request gets anomaly-modaled far more often
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

_DDG_HTML = "https://html.duckduckgo.com/html/"
_DDG_LITE = "https://lite.duckduckgo.com/lite/"
_MARGINALIA = "https://api.marginalia.nu/public/search/{q}?key=public&count=8"

_CHALLENGE_MARKERS = ("anomaly-modal", "challenge-form", "if this error persists",
                      "unfortunately, bots use duckduckgo")
_STRIP_TAGS = re.compile(
    r"<(script|style|nav|footer|header|form|svg|noscript|aside|button)"
    r"[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")

_SEARCH_TTL_S = 600
_FETCH_TTL_S = 900
_SEARCH_DEBOUNCE_S = 2.0
_MAX_REDIRECTS = 4
_MAX_BODY = 1_500_000          # read cap — bigger pages aren't read fully anyway


class WebError(Exception):
    """Honest failure — dispatch renders these as `error: web …` results."""


def _decode_ddg_url(href: str) -> str:
    """DDG wraps outbound hrefs in //duckduckgo.com/l/?uddg=<quoted>."""
    if "uddg=" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if u := qs.get("uddg"):
            return urllib.parse.unquote(u[0])
    if href.startswith("//"):
        return "https:" + href
    return href


def _parse_ddg_html(page: str) -> list[dict]:
    """html.duckduckgo.com markup: a.result__a + div/a.result__snippet."""
    out = []
    links = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        page, re.DOTALL)
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', page, re.DOTALL)
    for i, (href, title) in enumerate(links):
        out.append({
            "title": html.unescape(_TAG.sub("", title)).strip(),
            "url": _decode_ddg_url(html.unescape(href)),
            "snippet": html.unescape(_TAG.sub("", snippets[i])).strip()
            if i < len(snippets) else "",
        })
    return out


def _parse_ddg_lite(page: str) -> list[dict]:
    """lite markup is a table: a.result-link + td.result-snippet."""
    out = []
    links = re.findall(
        r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        page, re.DOTALL)
    snippets = re.findall(
        r'class="result-snippet"[^>]*>(.*?)</td>', page, re.DOTALL)
    for i, (href, title) in enumerate(links):
        out.append({
            "title": html.unescape(_TAG.sub("", title)).strip(),
            "url": _decode_ddg_url(html.unescape(href)),
            "snippet": html.unescape(_TAG.sub("", snippets[i])).strip()
            if i < len(snippets) else "",
        })
    return out


def _is_challenged(page: str) -> bool:
    low = page.lower()
    return any(m in low for m in _CHALLENGE_MARKERS)


def _host_ips(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve host → every A/AAAA it maps to (sync; called in executor)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise WebError(f"DNS failed for {host}") from e
    ips = []
    for fam, *_rest, sockaddr in infos:
        if fam in (socket.AF_INET, socket.AF_INET6):
            ips.append(ipaddress.ip_address(sockaddr[0]))
    return ips


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _host_literal(host: str) -> ipaddress._BaseAddress | None:
    """Catch literal-IP tricks: 127.0.0.1, [::1], decimal-int, 0x7f… forms."""
    h = host.strip("[]")
    for cand in (h,):
        try:
            return ipaddress.ip_address(cand)
        except ValueError:
            pass
    try:  # decimal/octal/hex single-int IPv4 e.g. http://2130706433/
        return ipaddress.ip_address(int(h, 0))
    except (ValueError, OverflowError):
        return None


class WebSearch:
    """One shared client per coach — debounce + TTL caches live here."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._own = client is None
        self._debounce = asyncio.Lock()
        self._last_search = 0.0
        self._search_cache: dict[str, tuple[float, str]] = {}
        self._fetch_cache: dict[str, tuple[float, str]] = {}

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=_HEADERS, timeout=httpx.Timeout(12.0, connect=5.0),
                follow_redirects=False,  # redirects re-run the SSRF check
                max_redirects=0)
        return self._client

    async def aclose(self) -> None:
        if self._own and self._client:
            await self._client.aclose()

    # ---------------- search ----------------

    async def search(self, query: str, max_results: int = 6) -> str:
        q = (query or "").strip()[:200]
        if not q:
            return "error: empty query"
        max_results = max(1, min(int(max_results or 6), 10))
        key = q.lower()
        if hit := self._cached(self._search_cache, key, _SEARCH_TTL_S):
            return "CACHED: " + hit
        try:
            async with self._debounce:
                gap = _SEARCH_DEBOUNCE_S - (time.time() - self._last_search)
                if gap > 0:
                    await asyncio.sleep(gap)
                self._last_search = time.time()
                results = await self._search_chain(q)
        except WebError as e:
            return f"error: web search failed — {e}"
        except (TimeoutError, httpx.HTTPError) as e:
            return f"error: web search failed — {type(e).__name__}"
        if not results:
            return (f"no results for '{q}' — rephrase with different terms "
                    "(add CVE id, error string, or 'exploit')")
        out = [f"{i}. {r['title']}\n   {r['url']}"
               + (f"\n   {r['snippet'][:200]}" if r["snippet"] else "")
               for i, r in enumerate(results[:max_results], 1)]
        text = f"{len(results[:max_results])} results for '{q}':\n" + "\n".join(out)
        self._search_cache[key] = (time.time(), text)
        return text

    async def _search_chain(self, q: str) -> list[dict]:
        last_err: Exception | None = None
        for fn in (self._ddg_html, self._ddg_lite, self._marginalia):
            try:
                if results := await fn(q):
                    return results
            except (TimeoutError, WebError, httpx.HTTPError) as e:
                last_err = e
        if last_err:
            raise WebError(f"all engines unavailable ({last_err})")
        return []

    async def _ddg_post(self, endpoint: str, q: str,
                        parser) -> list[dict]:
        c = await self._http()
        r = await c.post(endpoint, data={"q": q})
        if r.status_code in (202, 301, 302, 403, 429):
            raise WebError(f"{endpoint.split('/')[2]} challenged "
                           f"(HTTP {r.status_code})")
        r.raise_for_status()
        if _is_challenged(r.text):
            raise WebError(f"{endpoint.split('/')[2]} challenge page")
        return parser(r.text)

    async def _ddg_html(self, q: str) -> list[dict]:
        return await self._ddg_post(_DDG_HTML, q, _parse_ddg_html)

    async def _ddg_lite(self, q: str) -> list[dict]:
        return await self._ddg_post(_DDG_LITE, q, _parse_ddg_lite)

    async def _marginalia(self, q: str) -> list[dict]:
        c = await self._http()
        r = await c.get(_MARGINALIA.format(q=urllib.parse.quote(q)))
        r.raise_for_status()
        data = r.json()
        items = data.get("results") if isinstance(data, dict) else data
        out = []
        for it in items or []:
            if isinstance(it, dict) and it.get("url"):
                out.append({"title": str(it.get("title") or "")[:200],
                            "url": str(it["url"]),
                            "snippet": str(it.get("description") or "")[:300]})
        return out

    # ---------------- fetch ----------------

    async def fetch(self, url: str, max_chars: int = 8000) -> str:
        u = (url or "").strip()[:500]
        if not u:
            return "error: empty url"
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        key = u.lower()
        if hit := self._cached(self._fetch_cache, key, _FETCH_TTL_S):
            return "CACHED: " + hit
        try:
            body, final_url, ctype = await self._get_guarded(u)
        except WebError as e:
            return f"error: web fetch failed — {e}"
        except (TimeoutError, httpx.HTTPError) as e:
            return f"error: web fetch failed — {type(e).__name__}"
        if not any(t in ctype for t in
                   ("text/html", "text/plain", "application/json",
                    "application/xml", "text/xml", "text/markdown")):
            return (f"error: binary/unsupported content-type '{ctype}' "
                    f"({len(body)} bytes) — if it matters, download it with "
                    "exec_in_kali curl/wget and inspect locally")
        text = self._extract(body)
        if not text.strip():
            return f"error: page at {final_url} yielded no readable text"
        suffix = ""
        if len(text) > max_chars:
            suffix = f"\n…[truncated — {len(text) - max_chars} more chars]"
            text = text[:max_chars]
        out = f"URL: {final_url}\n\n{text}{suffix}"
        self._fetch_cache[key] = (time.time(), out)
        return out

    async def _get_guarded(self, url: str) -> tuple[bytes, str, str]:
        """GET with SSRF check on the URL AND every redirect hop."""
        c = await self._http()
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            parsed = urllib.parse.urlparse(current)
            if parsed.scheme not in ("http", "https"):
                raise WebError(f"scheme '{parsed.scheme}' not allowed")
            host = parsed.hostname or ""
            if not host:
                raise WebError("no hostname")
            if host.endswith((".local", ".internal", ".lan")):
                raise WebError(f"{host} looks like a LAN name — denied")
            if (lit := _host_literal(host)) and _blocked_ip(lit):
                raise WebError(f"{host} is private/lab space — denied")
            loop = asyncio.get_running_loop()
            ips = await loop.run_in_executor(None, _host_ips, host)
            if not ips:
                raise WebError(f"DNS returned nothing for {host}")
            bad = next((str(ip) for ip in ips if _blocked_ip(ip)), None)
            if bad:
                raise WebError(f"{host} resolves to {bad} "
                               "(private/lab space) — denied")
            r = await c.get(current, headers={
                "Sec-Fetch-Site": "cross-site",
            })
            if r.is_redirect and (loc := r.headers.get("location")):
                current = urllib.parse.urljoin(current, loc)
                continue
            if r.status_code == 429:
                raise WebError("rate-limited (HTTP 429)")
            if r.status_code in (401, 403):
                raise WebError(f"access denied by site (HTTP {r.status_code})")
            if r.status_code >= 500:
                raise WebError(f"site error (HTTP {r.status_code})")
            r.raise_for_status()
            body = r.content[:_MAX_BODY]
            ctype = r.headers.get("content-type", "").split(";")[0].lower()
            return body, str(r.url), ctype
        raise WebError(f"too many redirects (>{_MAX_REDIRECTS})")

    def _extract(self, body: bytes) -> str:
        raw = body.decode("utf-8", errors="replace")
        if trafilatura is not None:
            try:
                if text := trafilatura.extract(
                        raw, include_comments=False, include_tables=True,
                        favor_recall=True):
                    return text
            except Exception:  # noqa: S110 — quirk, crude stripper below
                pass
        page = _STRIP_TAGS.sub(" ", raw)
        page = _TAG.sub(" ", page)
        page = html.unescape(page)
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        return "\n".join(lines)

    # ---------------- cache ----------------

    @staticmethod
    def _cached(cache: dict, key: str, ttl: float) -> str | None:
        if (e := cache.get(key)) and time.time() - e[0] < ttl:
            return e[1]
        cache.pop(key, None)
        return None
