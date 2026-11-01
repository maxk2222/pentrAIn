"""percept — output normalization: ANSI strip, tool parsers, compression."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.percept import normalize, parse_output, parse_worker_report, strip_ansi


def test_strip_ansi_removes_escapes_and_controls():
    raw = "\x1b[32mgreen\x1b[0m plain\x07bell\x08"
    assert strip_ansi(raw) == "green plainbell"


def test_parse_nmap_ports_to_facts():
    out = ("Nmap scan report for web01 (10.1.10.21)\n"
           "22/tcp open  ssh     OpenSSH 9.2p1\n"
           "80/tcp open  http    nginx\n")
    d = parse_output("nmap -sV 10.1.10.21", out)
    assert d["ports"]["10.1.10.21"][22].startswith("OpenSSH")
    assert d["ports"]["10.1.10.21"][80] == "nginx"
    assert d["names"]["10.1.10.21"] == ["web01"]


def test_parse_getent_names():
    d = parse_output("getent hosts api01", "10.1.10.30   api01 pentrain-api01\n")
    assert d["names"]["10.1.10.30"] == ["api01", "pentrain-api01"]


def test_parse_hydra_cred_with_host():
    out = "[22][ssh] host: 10.1.10.21   login: svc   password: s3cret\n"
    d = parse_output("hydra -l svc -P wl ssh://10.1.10.21", out)
    assert d["creds"] == [{"user": "svc", "secret": "s3cret",
                           "host": "10.1.10.21"}]


def test_parse_generic_cred_pair():
    d = parse_output("cat notes.txt", "login: admin password: hunt3r\n")
    assert d["creds"][0]["secret"] == "hunt3r"


def test_parse_sudo_wrapped_tool_found():
    out = "Discovered open port 443/tcp on 10.1.10.9\n"
    d = parse_output("sudo masscan -p443 10.1.10.9 --rate=100", out)
    assert d["ports"]["10.1.10.9"][443] == ""


def test_parse_never_raises_on_garbage():
    d = parse_output("ls", "\x00\x01\xff\xfe" * 50)
    assert isinstance(d["ips"], set)


def test_normalize_status_inference():
    assert normalize("id", "uid=0\n", 0).status == "ok"
    assert normalize("id", "", 0).status == "no_change"
    assert normalize("id", "boom", 1).status == "error"
    assert normalize("sleep 99", "partial", None, timed_out=True).status == "busy"


def test_normalize_appends_exit_code():
    p = normalize("id", "uid=0\n", 0)
    assert p.reply.endswith("(exit 0)")
    p = normalize("id", "", 0)
    assert p.reply == "exit 0"


def test_normalize_elides_middle_keeps_tail():
    lines = [f"line {i}" for i in range(80)]
    p = normalize("nmap x", "\n".join(lines), 0)
    assert "… 52 lines elided" in p.reply
    assert "line 0" in p.reply and "line 79" in p.reply
    assert "line 40" not in p.reply


def test_normalize_never_raises_on_weird_input():
    p = normalize("x", None, None)   # type: ignore[arg-type]
    assert p.reply == ""


def test_parse_worker_report_pure_json():
    rep = '{"summary": "found share", "creds": [{"user": "u", "secret": "p", "host": "10.1.1.5"}], "next": "mount it"}'
    d = parse_worker_report(rep)
    assert d["summary"] == "found share"
    assert d["creds"][0]["secret"] == "p"


def test_parse_worker_report_wrapped_in_prose():
    rep = ('Here is my final report:\n```json\n{"findings": ["smb open"], '
           '"hosts": [{"ip": "10.1.1.5", "ports": {"445": "smb"}}]}\n```')
    d = parse_worker_report(rep)
    assert d["findings"] == ["smb open"]
    assert d["hosts"][0]["ip"] == "10.1.1.5"


def test_parse_worker_report_prose_returns_none():
    assert parse_worker_report("REPORT: 22/80 open, share listed") is None
    assert parse_worker_report("") is None
    assert parse_worker_report('{"unrelated": 1}') is None


def test_normalize_flags_silent_login_redirect():
    """Empty-body response to a login POST = silent 302-back-to-form —
    curl exits 0 so without the annotation the model reads auth as
    established (session 39 DVWA loop)."""
    from coach.percept import normalize
    p = normalize(
        "curl -s -c jar 'http://t/login.php' -d 'username=admin&password=x'",
        "", 0)
    assert "auth unverified" in p.reply
    # same login-shaped redirect body also triggers
    p2 = normalize(
        "curl -s -b jar -c jar 'http://t/dvwa/login.php' -d 'u=1'",
        '<meta http-equiv="refresh" content="0; URL=login.php">', 0)
    assert "auth unverified" in p2.reply
    # a real response body is not flagged
    p3 = normalize(
        "curl -s -c jar 'http://t/login.php' -d 'u=1'",
        "Welcome admin — dashboard …" * 30, 0)
    assert "auth unverified" not in p3.reply
    # GETs and non-login endpoints never trigger
    p4 = normalize("curl -s 'http://t/index.php'", "", 0)
    assert "auth unverified" not in p4.reply


def test_hidden_form_inputs_become_findings():
    """HTML hidden fields (user_token/csrf) land in findings WITH the value —
    the token stops being a recipe step and becomes a usable fact."""
    from coach.percept import parse_output
    html = ("<form action='login.php'><input type='hidden' name='user_token' "
            "value='897d1126f1351f7abb9c6e9b183b4f4b' /></form>")
    d = parse_output("curl -s http://t/login.php", html)
    assert "form:user_token=897d1126f1351f7abb9c6e9b183b4f4b" in d["findings"]
    # name-first ordering also parses
    d2 = parse_output("curl x", "<input name='csrf' value='abc' type=\"hidden\">")
    assert any(f.startswith("form:csrf=") for f in d2["findings"])


def test_env_secrets_and_endpoints_become_facts():
    from coach.percept import parse_output
    out = ("DEPLOY_USER=deploy\nDEPLOY_PASS=Nordm#arkt!25\n"
           "API_TOKEN=nm-api-9f3d77c1\nAPI_URL=http://172.18.0.4:9000\n"
           "HOME=/root\nPATH=/usr/bin:/bin")
    d = parse_output("cat config.env", out)
    pairs = {(c["user"], c["secret"]) for c in d["creds"]}
    assert ("API_TOKEN", "nm-api-9f3d77c1") in pairs
    assert ("DEPLOY_PASS", "Nordm#arkt!25") in pairs
    assert not any(c["user"] in ("HOME", "PATH") for c in d["creds"])
    assert any("endpoint:API_URL=http://172.18.0.4:9000" == f
               for f in d["findings"])
    assert "172.18.0.4" in d["ips"]
