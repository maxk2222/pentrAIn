"""Research tools — search_exploitdb (offline), query_vuln_db + rss_feed
(internet-gated), search_technique (layered offline→online)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach import research
from coach import tools as toolmod
from coach.loop import SessionCoach, _render_searchsploit


class FakeClient:
    def __init__(self, internet=True, session_tools="searchsploit"):
        self.execs = []
        self.ctx = {
            "session": {"id": 1, "state": "active", "autonomy_level": 4,
                        "coach_enabled": True, "subagents_enabled": True,
                        "kali_internet": internet},
            "session_tools": session_tools,
            "quest": {"title": "Q", "track": "t", "tier": 1,
                      "briefing": "b", "coach_context": "",
                      "checkpoints": [], "escalation": {},
                      "targets": []},
            "flags": [], "checkpoints_hit": [], "telemetry_tail": [],
            "messages": [], "exec_count": 0,
            "profile": {"track_levels": {"t": 1}},
        }

    async def send_chat(self, *a, **k): return {}
    async def session_context(self, sid): return self.ctx
    async def log_action(self, *a, **k): return {}
    async def log_denial(self, *a, **k): return {}
    async def stream_draft(self, *a, **k): pass
    async def send_activity(self, *a, **k): pass
    async def send_agents(self, *a, **k): pass
    async def report_llm_usage(self, *a, **k): return {}

    async def exec_in_kali(self, sid, cmd, window=None):
        self.execs.append(cmd)
        return {"out": "ok", "exitcode": 0, "visible": True}


class FakeLlm:
    model = "fake"

    async def chat(self, *a, **k):
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


async def _coach(internet=True, session_tools="searchsploit"):
    c = FakeClient(internet=internet, session_tools=session_tools)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    return coach


async def _dispatch(coach, tool, args):
    """Straight into the dispatch layer — same path tool_calls take."""
    return await coach._dispatch_inner({"type": tool, **args})


# ---------------- tool surface ----------------

def test_tool_surface():
    l4 = {t["function"]["name"] for t in toolmod.tools_for_level(4)}
    for t in ("search_exploitdb", "query_vuln_db", "rss_feed",
              "search_technique"):
        assert t in l4
    workers = {t["function"]["name"] for t in toolmod.worker_tools()}
    assert "search_exploitdb" in workers
    assert "search_technique" in workers
    # research-heavy tools stay parent-side — workers operate, don't browse
    assert "query_vuln_db" not in workers
    assert "rss_feed" not in workers


# ---------------- search_exploitdb ----------------

async def test_search_exploitdb_execs_and_parses():
    coach = await _coach()
    _spoke, _res = await _dispatch(coach, "search_exploitdb",
                                   {"query": "vsftpd 2.3.4"})
    assert coach.client.execs
    cmd = coach.client.execs[0]
    assert "searchsploit --json" in cmd and "vsftpd 2.3.4" in cmd
    await coach.stop()


async def test_search_exploitdb_needs_gate():
    coach = await _coach(session_tools="nmap curl")   # no searchsploit
    _spoke, res = await _dispatch(coach, "search_exploitdb",
                                 {"query": "apache"})
    assert res.startswith("error:") and "KALI_TOOLS" in res
    assert not coach.client.execs          # never reached the pane
    await coach.stop()


def test_render_searchsploit_json():
    out = (
        '{"RESULTS_EXPLOIT": [{"EDB-ID": "49757", "Title": "vsftpd 2.3.4",'
        ' "Type": "remote", "Platform": "unix", "Path": "/x/49757.py",'
        ' "Verified": "1"}], "RESULTS_SHELLCODE": []}')
    r = _render_searchsploit(out, 0, "vsftpd")
    assert "EDB-49757*" in r and "remote/unix" in r and "/x/49757.py" in r
    assert "no exploit-db hits" in _render_searchsploit(
        '{"RESULTS_EXPLOIT": [], "RESULTS_SHELLCODE": []}', 0, "zzz")
    assert "not json" in _render_searchsploit("bash: not found", 127, "x")


# ---------------- query_vuln_db / rss_feed gates ----------------

async def test_vuln_db_denied_offline():
    coach = await _coach(internet=False)
    _spoke, res = await _dispatch(coach, "query_vuln_db",
                                 {"query": "CVE-2024-4577"})
    assert res.startswith("denied: web")
    await coach.stop()


async def test_rss_denied_offline_and_unknown_feed():
    coach = await _coach(internet=False)
    _spoke, res = await _dispatch(coach, "rss_feed", {"feed": "exploitdb"})
    assert res.startswith("denied: web")
    coach.ctx["session"]["kali_internet"] = True
    _spoke, res = await _dispatch(coach, "rss_feed", {"feed": "bogus"})
    assert res.startswith("error: unknown feed")
    await coach.stop()


# ---------------- research client (parsing paths) ----------------

_NVD_JSON = {"vulnerabilities": [{"cve": {
    "id": "CVE-2024-4577",
    "descriptions": [{"lang": "en", "value": "PHP CGI RCE"}],
    "metrics": {"cvssMetricV31": [{"cvssData": {
        "baseScore": 9.8, "baseSeverity": "CRITICAL"}}]},
    "weaknesses": [{"description": [{"lang": "en", "value": "CWE-78"}]}],
    "references": [{"url": "u1"}, {"url": "u2"}]}}]}


class _FakeResp:
    def __init__(self, status=200, data=None, content=b""):
        self.status_code = status
        self._d = data
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._d


class _FakeHttp:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        return self.resp


async def test_vuln_detail_with_kev_flag():
    rc = research.ResearchClient(client=_FakeHttp(_FakeResp(data=_NVD_JSON)))
    rc._nvd_lock = _NopLock()          # skip the 6.5s debounce in tests
    out = await rc.vuln("CVE-2024-4577")
    assert "CVE-2024-4577" in out and "9.8" in out and "CWE-78" in out


class _NopLock:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


async def test_vuln_rate_limit_is_honest():
    rc = research.ResearchClient(client=_FakeHttp(_FakeResp(status=403)))
    rc._nvd_lock = _NopLock()
    out = await rc.vuln("apache")
    assert "rate-limited" in out and out.startswith("error:")


def test_xml_items_rss_and_atom():
    rss = b"""<rss version="2.0"><channel><title>EDB</title>
      <item><title>e1</title><link>u1</link>
      <pubDate>Mon, 01 Jan 2024</pubDate>
      <description>desc one</description></item></channel></rss>"""
    title, items = research._xml_items(rss, 5)
    assert title == "EDB" and items[0]["title"] == "e1" \
        and items[0]["link"] == "u1" and "desc one" in items[0]["desc"]
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <title>GHSA</title>
      <entry><title>a1</title><link href="u9"/>
      <published>2024-01-02</published><summary>s1</summary></entry>
      </feed>"""
    title, items = research._xml_items(atom, 5)
    assert title == "GHSA" and items[0]["link"] == "u9"


async def test_feed_list_and_cache():
    rc = research.ResearchClient(client=_FakeHttp(_FakeResp(content=b"")))
    out = await rc.feed("list")           # list path needs no http at all
    assert "exploitdb" in out and "packetstorm" in out


# ---------------- search_technique ----------------

async def test_technique_vendored_hits_real_refs():
    coach = await _coach(internet=False)
    _spoke, res = await _dispatch(
        coach, "search_technique",
        {"query": "kerberoast", "source": "vendored"})
    assert "kerberoast" in res.lower()
    assert "ref file" in res
    await coach.stop()


async def test_technique_named_site_denied_offline():
    coach = await _coach(internet=False)
    _spoke, res = await _dispatch(
        coach, "search_technique",
        {"query": "sqli", "source": "hacktricks"})
    assert res.startswith("denied: web")
    await coach.stop()


async def test_technique_unknown_source():
    coach = await _coach()
    _spoke, res = await _dispatch(
        coach, "search_technique",
        {"query": "sqli", "source": "bogus"})
    assert res.startswith("error: unknown source")
    await coach.stop()


def test_grep_refs_multi_term_and_missing_dir(tmp_path):
    # terms must ALL be present in a file for it to qualify
    (tmp_path / "a.md").write_text("kerberoast uses TGS tickets\nroast them")
    (tmp_path / "b.md").write_text("sudo -l lists\nnothing about tickets")
    out = research.grep_refs("kerberoast tickets", tmp_path)
    assert "a.md" in out and "b.md" not in out
    assert research.grep_refs("x", tmp_path / "nope").startswith("error:")
