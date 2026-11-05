"""Curated security research for the coach — structured vuln intel + feeds.

Two coach-side tools ride this module (query_vuln_db / rss_feed); dispatch
gates both on the session's kali_internet flag exactly like web_search —
the gate is lab-isolation policy, not connectivity, since the coach host
always has egress.

Sources — all key-free:

  NVD API 2.0   services.nvd.nist.gov — CVE detail + keyword search.
                Public rate limit is 5 req / 30s, so calls serialize
                through a >=6.5s debounce and answers cache for an hour.
                A 403 is rendered honestly ("rate-limited") — never as
                empty results.
  CISA KEV      known exploited vulnerabilities catalog — one JSON pull
                cached ~6h; matched CVEs get a [KEV] mark so "is it
                exploited in the wild" is a lookup, not a guess.
  RSS/Atom      curated exploit/vuln feed map parsed with stdlib
                xml.etree — RSS2 <item> and Atom <entry> both handled.

Everything degrades honestly: feed rot, rate limits and DNS failures
come back as `error:` results the model can react to, never as silence.
"""
from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

_NVD_CVE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_KEV_URL = ("https://www.cisa.gov/sites/default/files/feeds/"
            "known_exploited_vulnerabilities.json")

_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
       "Gecko/20100101 Firefox/128.0")
_HEADERS = {"User-Agent": _UA, "Accept": "application/json,*/*;q=0.8"}

_NVD_DEBOUNCE_S = 6.5        # anonymous tier: 5 req / 30s rolling
_NVD_CACHE_TTL_S = 3600
_KEV_TTL_S = 6 * 3600
_FEED_TTL_S = 600
_MAX_BODY = 1_500_000

# curated feed map — exploit/vuln sources first (that's what moves a
# session forward); general news feeds ride along for the free lab.
# Dead endpoints degrade to honest `error:` results — the map is the
# discovery surface, `rss_feed list` renders it.
FEEDS: dict[str, tuple[str, str]] = {
    "exploitdb": ("https://www.exploit-db.com/rss.xml",
                  "newest public exploits on Exploit-DB"),
    "packetstorm": ("https://packetstormsecurity.com/files/feed.xml",
                    "daily files — exploits, tools, advisories"),
    "cisa-alerts": ("https://www.cisa.gov/cybersecurity-advisories/all.xml",
                    "CISA advisories + ICS alerts"),
    "github-advisories": ("https://github.com/advisories.atom",
                          "GitHub Security Advisories (GHSA)"),
    "thehackernews": ("https://feeds.feedburner.com/TheHackersNews",
                      "security news headlines"),
    "r-netsec": ("https://www.reddit.com/r/netsec/.rss",
                 "r/netsec — research writeups, tool drops"),
}

_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)

# vendored technique excerpts — curated copies of upstream references
# (PayloadsAllTheThings etc.) refreshed via scripts/sync_tech_refs.py.
# Baseline that works fully offline: no kali exec, no internet.
REFS_DIR = Path(__file__).parent / "knowledge" / "refs"

# named technique sources for site-scoped web_search — the online leg
# of search_technique. Key = tool arg, value = site: operator domain.
TECHNIQUE_SITES: dict[str, str] = {
    "hacktricks": "book.hacktricks.xyz",
    "payloadsallthethings": "github.com/swisskyrepo/PayloadsAllTheThings",
    "owasp": "cheatsheetseries.owasp.org",
    "gtfobins": "gtfobins.github.io",
    "lolbas": "lolbas-project.github.io",
}


class ResearchError(Exception):
    """Honest failure — dispatch renders these as `error:` results."""


def grep_refs(query: str, refs_dir: Path = REFS_DIR,
              max_lines: int = 24) -> str:
    """AND-of-terms grep over vendored technique refs — coach-side, so it
    works in a fully offline lab. A file qualifies only when EVERY query
    term appears in it; shown lines are those matching any term."""
    terms = [t for t in (query or "").split() if len(t) > 1][:4]
    if not terms:
        return "error: empty query"
    if not refs_dir.is_dir():
        return ("error: no vendored refs (knowledge/refs missing) — "
                "try source=kali or a named site source")
    pats = [re.compile(re.escape(t), re.IGNORECASE) for t in terms]
    any_pat = re.compile("|".join(re.escape(t) for t in terms),
                         re.IGNORECASE)
    hits: list[tuple[int, str, list[str]]] = []
    for f in sorted(refs_dir.rglob("*.md")):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace"
                                ).splitlines()
        except OSError:
            continue
        text_matched = [any(p.search(ln) for ln in lines[:400])
                        for p in pats]
        if not all(text_matched):
            continue
        ctx: list[str] = []
        for i, ln in enumerate(lines[:400]):
            if any_pat.search(ln):
                ctx.append(f"{f.name}:{i + 1}  {ln.strip()[:150]}")
                if i + 1 < len(lines) and lines[i + 1].strip():
                    ctx.append(f"    {lines[i + 1].strip()[:150]}")
                if len(ctx) > 5:
                    break
        if ctx:
            hits.append((sum(len(p.findall(" ".join(lines))) for p in pats),
                         f.name, ctx))
    if not hits:
        return ""
    hits.sort(reverse=True)
    shown: list[str] = []
    for _n, _f, ctx in hits:
        shown.extend(ctx)
        if len(shown) >= max_lines:
            break
    q = " ".join(terms)
    return (f"{len(hits)} ref file(s) match '{q}':\n"
            + "\n".join(shown[:max_lines])
            + "\n(full files: coach/knowledge/refs — or web_fetch the "
              "upstream source when online)")


def _cvss(metrics: dict) -> str:
    """Best available CVSS v3.x base score + severity, else v2 fallback."""
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        for m in metrics.get(key) or []:
            data = m.get("cvssData") or {}
            score = data.get("baseScore")
            sev = (data.get("baseSeverity") or m.get("baseSeverity")
                   or "").upper()
            if score is not None:
                return f"{score} {sev}".strip()
    return "n/a"


def _desc(cve: dict) -> str:
    for d in cve.get("descriptions") or []:
        if d.get("lang") == "en":
            return str(d.get("value") or "")
    return ""


def _cwes(cve: dict) -> str:
    out = []
    for w in cve.get("weaknesses") or []:
        for d in w.get("description") or []:
            if d.get("lang") == "en" and d.get("value", "").startswith("CWE"):
                out.append(d["value"])
    return ",".join(dict.fromkeys(out))


def _fmt_cve(cve: dict, kev: dict[str, dict]) -> str:
    cid = cve.get("id") or "?"
    mark = ""
    if cid in kev:
        k = kev[cid]
        mark = (f" [KEV exploited — due {k.get('dueDate') or '?'}]"
                + (" RANSOMWARE" if k.get("knownRansomwareCampaignUse")
                                   == "Known" else ""))
    refs = len(cve.get("references") or [])
    cwe = f" {_cwes(cve)}" if _cwes(cve) else ""
    desc = " ".join(_desc(cve).split())[:280]
    return (f"{cid} — CVSS {_cvss(cve.get('metrics') or {})}{cwe}{mark}\n"
            f"  {desc}\n  {refs} reference(s) — details: "
            f"https://nvd.nist.gov/vuln/detail/{cid}")


def _xml_items(raw: bytes, limit: int) -> tuple[str, list[dict]]:
    """RSS2 <item> and Atom <entry> → uniform dicts. Feed title + items."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ResearchError(f"feed is not parseable XML ({e})") from e
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    title = (root.findtext(f".//{ns}channel/{ns}title")
             or root.findtext(f"{ns}title") or "feed").strip()
    items: list[dict] = []
    # RSS2
    for it in root.findall(f".//{ns}channel/{ns}item"):
        items.append({
            "title": (it.findtext(f"{ns}title") or "").strip(),
            "link": (it.findtext(f"{ns}link") or "").strip(),
            "date": (it.findtext(f"{ns}pubDate")
                     or it.findtext(f"{ns}date") or "").strip(),
            "desc": re.sub(r"<[^>]+>", " ",
                           it.findtext(f"{ns}description") or "").strip(),
        })
    # Atom
    if not items:
        for it in root.findall(f"{ns}entry") or root.findall(f".//{ns}entry"):
            link = ""
            for l in it.findall(f"{ns}link"):
                if l.get("href"):
                    link = l.get("href")
                    break
            items.append({
                "title": (it.findtext(f"{ns}title") or "").strip(),
                "link": link,
                "date": (it.findtext(f"{ns}published")
                         or it.findtext(f"{ns}updated") or "").strip(),
                "desc": re.sub(r"<[^>]+>", " ",
                               it.findtext(f"{ns}summary") or "").strip(),
            })
    return title, items[:limit]


class ResearchClient:
    """One client per coach — NVD debounce + KEV/feed/query caches."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._own = client is None
        self._nvd_lock = asyncio.Lock()
        self._last_nvd = 0.0
        self._nvd_cache: dict[str, tuple[float, str]] = {}
        self._kev: tuple[float, dict[str, dict]] = (0.0, {})
        self._feed_cache: dict[str, tuple[float, str]] = {}

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=_HEADERS, timeout=httpx.Timeout(15.0, connect=6.0),
                follow_redirects=True, max_redirects=3)
        return self._client

    async def aclose(self) -> None:
        if self._own and self._client:
            await self._client.aclose()

    # ---------------- KEV ----------------

    async def _kev_map(self) -> dict[str, dict]:
        ts, kev = self._kev
        if kev and time.time() - ts < _KEV_TTL_S:
            return kev
        try:
            c = await self._http()
            r = await c.get(_KEV_URL)
            r.raise_for_status()
            data = r.json()
            kev = {v["cveID"]: v for v in data.get("vulnerabilities") or []
                   if v.get("cveID")}
            self._kev = (time.time(), kev)
            return kev
        except (httpx.HTTPError, ValueError):
            return self._kev[1]           # stale KEV beats no KEV flag

    # ---------------- NVD ----------------

    async def vuln(self, query: str) -> str:
        q = (query or "").strip()[:120]
        if not q:
            return "error: empty query"
        key = q.lower()
        if (e := self._nvd_cache.get(key)) and time.time() - e[0] < _NVD_CACHE_TTL_S:
            return "CACHED: " + e[1]
        params: dict[str, str] = {}
        if m := _CVE_RE.search(q):
            params["cveId"] = m.group(0).upper()
        else:
            params["keywordSearch"] = q
            params["resultsPerPage"] = "5"
        try:
            async with self._nvd_lock:
                gap = _NVD_DEBOUNCE_S - (time.time() - self._last_nvd)
                if gap > 0:
                    await asyncio.sleep(gap)
                c = await self._http()
                r = await c.get(_NVD_CVE, params=params)
                self._last_nvd = time.time()
        except (TimeoutError, httpx.HTTPError) as e:
            return f"error: NVD query failed — {type(e).__name__}"
        if r.status_code == 403:
            return ("error: NVD rate-limited (anonymous tier is 5 req/30s) "
                    "— retry in half a minute or fall back to web_search")
        if r.status_code >= 400:
            return f"error: NVD returned HTTP {r.status_code}"
        try:
            vulns = (r.json().get("vulnerabilities") or [])
        except ValueError:
            return "error: NVD returned non-JSON"
        if not vulns:
            return (f"no NVD hits for '{q}' — keyword search matches CVE "
                    "descriptions only; try vendor+product names or a CVE id")
        kev = await self._kev_map()
        rows = [_fmt_cve(v.get("cve") or {}, kev) for v in vulns[:5]]
        out = f"{len(rows)} NVD result(s) for '{q}':\n\n" + "\n\n".join(rows)
        self._nvd_cache[key] = (time.time(), out)
        return out

    # ---------------- feeds ----------------

    async def feed(self, name: str, count: int = 5) -> str:
        n = (name or "").strip().lower()
        if n in ("", "list"):
            rows = "\n".join(f"  {k} — {d} ({u})" for k, (u, d)
                             in FEEDS.items())
            return (f"curated feeds ({len(FEEDS)}):\n{rows}\n"
                    "call rss_feed with one of these names, or web_fetch "
                    "any other feed URL directly")
        if n not in FEEDS:
            return (f"error: unknown feed '{n}' — known: "
                    f"{', '.join(FEEDS)} (or 'list')")
        if (e := self._feed_cache.get(n)) and time.time() - e[0] < _FEED_TTL_S:
            return "CACHED: " + e[1]
        url, what = FEEDS[n]
        count = max(1, min(int(count or 5), 8))
        try:
            c = await self._http()
            r = await c.get(url)
            r.raise_for_status()
            body = r.content[:_MAX_BODY]
            title, items = _xml_items(body, count)
        except (TimeoutError, httpx.HTTPError) as e:
            return f"error: {n} feed failed — {type(e).__name__}"
        except ResearchError as e:
            return f"error: {n} feed failed — {e}"
        if not items:
            return f"error: {n} feed parsed but had no items"
        rows = []
        for i, it in enumerate(items, 1):
            date = it["date"][:16] if it["date"] else "?"
            rows.append(f"{i}. {it['title'][:110]}\n   {date} — {it['link']}"
                        + (f"\n   {it['desc'][:140]}" if it["desc"] else ""))
        out = (f"{title} ({n} — {what}), {len(items)} item(s):\n"
               + "\n".join(rows))
        self._feed_cache[n] = (time.time(), out)
        return out
