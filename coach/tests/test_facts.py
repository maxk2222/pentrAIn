"""FactsDB — deterministic session memory: extraction, bookkeeping, render."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.facts import FactsDB

NMAP_OUT = """
Nmap scan report for web01 (10.1.10.21)
Host is up (0.0020s latency).
PORT     STATE SERVICE
22/tcp   open  ssh     OpenSSH 9.2p1
80/tcp   open  http    nginx 1.18.0
3306/tcp closed mysql
"""

HYDRA_OUT = """
[22][ssh] host: 10.1.10.21   login: svc-backup   password: Backup2024!
1 of 1 target successfully completed
"""


def test_observe_output_nmap_ports_and_names():
    f = FactsDB()
    f.observe_output("nmap -sV 10.1.10.21", NMAP_OUT, 0)
    h = f.hosts["10.1.10.21"]
    assert h.names == {"web01"}
    assert h.ports[22].startswith("OpenSSH") and h.ports[80].startswith("nginx")
    assert 3306 not in h.ports                     # closed ports aren't facts
    # the scanned IP is intent (in the command), not discovery — output
    # seeding only whitelists IPs that appear WITHOUT being in the command
    assert "10.1.10.21" not in f.ips_seen


def test_observe_output_hydra_cred_valid_on_host():
    f = FactsDB()
    f.observe_output("hydra -l svc-backup -P wl.txt ssh://10.1.10.21",
                     HYDRA_OUT, 0)
    c = f.creds[0]
    assert c.user == "svc-backup" and c.secret == "Backup2024!"
    assert c.valid_on == {"10.1.10.21"}
    # a found cred is never "untested" for the objective tracker
    assert f.untested_creds() == []


def test_cmd_side_cred_marked_tested_on_target():
    f = FactsDB()
    f.observe_command("sshpass -p s3cret ssh deploy@10.1.10.22 id")
    c = f.creds[0]
    assert c.secret == "s3cret" and c.tested_on == {"10.1.10.22"}


def test_generic_cred_pairs_in_loot_output():
    f = FactsDB()
    f.observe_output("cat /srv/runbook.txt",
                     "backup job\nlogin: svc-backup password: Backup2024!\n", 0)
    assert any(c.secret == "Backup2024!" for c in f.creds)


def test_write_run_bookkeeping_from_exec():
    f = FactsDB()
    f.observe_output("cat > /root/solve.py << 'EOF'\nx\nEOF", "", 0)
    f.observe_output("cat > /root/solve.py << 'EOF'\ny\nEOF", "", 0)
    assert f.files["/root/solve.py"].writes == 2
    f.observe_output("python3 -u /root/solve.py", "boom", 1)
    assert f.files["/root/solve.py"].runs == 1
    assert f.files["/root/solve.py"].last_exit == 1


def test_telemetry_pending_write_confirmed_by_result():
    f = FactsDB()
    f.observe_command("cat > /tmp/x.sh << 'EOF'\nx\nEOF")
    f.mark_run_exit(0)
    f.observe_command("cat > /tmp/x.sh << 'EOF'\ny\nEOF")
    f.mark_run_exit(0)
    assert f.files["/tmp/x.sh"].writes == 2
    # a failed third write is an attempt, not a confirmed write
    f.observe_command("cat > /tmp/x.sh << 'EOF'\nz\nEOF")
    f.mark_run_exit(1)
    assert f.files["/tmp/x.sh"].writes == 2


def test_pending_marker_expires():
    f = FactsDB()
    f.observe_command("cat > /tmp/y.sh << 'EOF'\nx\nEOF")
    f._pending = (f._pending[0], f._pending[1], time.time() - 120)
    f.mark_run_exit(0)
    assert f.files["/tmp/y.sh"].writes == 0


def test_typed_input_no_write_run_bookkeeping():
    f = FactsDB()
    f.observe_output("<type> python3 /root/x.py", "", None)
    assert "/root/x.py" not in f.files


def test_recon_scans_counted_per_target():
    f = FactsDB()
    f.observe_command("nmap -sV 10.1.10.21")
    f.observe_command("nmap -p- 10.1.10.21")
    assert f.hosts["10.1.10.21"].scans == 2
    # identical command replayed (echo/restart replay) doesn't double-count
    f.observe_command("nmap -sV 10.1.10.21")
    assert f.hosts["10.1.10.21"].scans == 2


def test_unscanned_lists_only_unprobed_targets():
    f = FactsDB()
    targets = [{"name": "web01", "ip": "10.1.10.21"},
               {"name": "db01", "ip": "10.1.10.33"}]
    assert f.unscanned(targets) == ["web01", "db01"]
    f.observe_command("nmap 10.1.10.21")
    assert f.unscanned(targets) == ["db01"]


def test_flags_seen_submitted():
    f = FactsDB()
    assert f.flag_seen("pentrAIn{a1}") == 1
    assert f.flag_seen("pentrAIn{a1}") == 2
    f.flag_mark_submitted("pentrAIn{a1}", True)
    assert f.flags["pentrAIn{a1}"].accepted


def test_render_compact_sections():
    f = FactsDB()
    f.add_host("10.1.10.21", "web01")
    f.hosts["10.1.10.21"].ports[22] = "OpenSSH 9.2"
    f.add_cred("svc-backup", "Backup2024!", "runbook")
    f.observe_output("cat > /root/s.py << 'EOF'\nx\nEOF", "", 0)
    f.flag_seen("pentrAIn{a1}")
    out = f.render()
    assert out.startswith("FACTS:")
    assert "web01=10.1.10.21" in out and "22:OpenSSH" in out
    assert "svc-backup/Backup2024! (untested)" in out
    assert "/root/s.py script(1w)" in out
    assert "unsubmitted: pentrAIn{a1}" in out


def test_render_respects_max_chars():
    f = FactsDB()
    for i in range(12):
        f.add_host(f"10.1.10.{10 + i}")
        f.hosts[f"10.1.10.{10 + i}"].ports[80] = "http"
    out = f.render(400)
    assert len(out) <= 400 and out.startswith("FACTS:")


def test_render_empty_when_no_facts():
    assert FactsDB().render() == ""


def test_apply_worker_report_merges():
    f = FactsDB()
    n = f.apply_worker_report("w1", {
        "creds": [{"user": "api", "secret": "tok", "host": "10.1.10.22"}],
        "hosts": [{"ip": "10.1.10.22", "name": "app01",
                   "ports": {"8080": "http"}}],
        "findings": ["app01 leaks /debug"]})
    assert n["creds"] == 1 and n["ports"] == 1
    assert f.creds[0].valid_on == {"10.1.10.22"}
    assert f.hosts["10.1.10.22"].ports[8080] == "http"
    assert f.hosts["10.1.10.22"].names == {"app01"}


def test_render_compact_keeps_findings():
    f = FactsDB()
    for i in range(12):
        f.add_host(f"10.1.10.{10 + i}")
        f.hosts[f"10.1.10.{10 + i}"].ports[80] = "http"
    f.apply_worker_report("w1", {
        "findings": ["endpoint:API_URL=http://172.18.0.4:9000"]})
    out = f.render(400)
    assert len(out) <= 400
    assert "endpoint:API_URL=http://172.18.0.4:9000" in out


def test_denials_merge_and_render_blocked():
    from coach.facts import FactsDB
    f = FactsDB()
    f.apply_delta({"denials": ["denied:sudo@shop01", "denied:docker@shop01"]})
    f.apply_delta({"denials": ["denied:sudo@shop01"]})   # dedup
    out = f.render()
    assert "blocked:" in out and "sudo@shop01" in out
    assert f.denials == ["denied:sudo@shop01", "denied:docker@shop01"]
    # compact render keeps the blocked line — that's the whole point
    for i in range(12):
        f.add_host(f"10.1.10.{10 + i}")
        f.hosts[f"10.1.10.{10 + i}"].ports[80] = "http"
    out = f.render(400)
    assert "blocked:" in out and "sudo@shop01" in out


def test_reads_count_via_observe_and_survive_replay():
    from coach.facts import FactsDB
    f = FactsDB()
    f.observe_output("cat /tmp/config.env", "A=1", 0)
    # ssh-wrapped read counts too (the old ^-anchored guard missed pivots)
    f.observe_output("sshpass -p 'x' ssh u@h 'cat /etc/secret.conf'",
                     "k=v", 0)
    # writes are NOT reads
    f.observe_output("cat > /tmp/w.py <<'EOF'\nx\nEOF", "", 0)
    assert f.files["/tmp/config.env"].reads == 1
    # ssh-wrapped reads key the file by host — /etc/secret.conf on h is a
    # DIFFERENT file than on Kali (s46: agent searched Kali /tmp for loot
    # written on shop01 — the fact must say WHERE the file lives)
    assert f.files["/etc/secret.conf@h"].reads == 1
    assert "/tmp/w.py" not in f.files or f.files["/tmp/w.py"].reads == 0


def test_reads_reset_after_mutation():
    """s54: report.txt rewritten by each report.sh run — a re-read after a
    confirmed write/run sees FRESH content and must not hit the 3x deny."""
    from coach.facts import FactsDB
    f = FactsDB()
    for _ in range(3):
        f.observe_output("cat /root/report.txt", "SERVICES=x", 0)
    assert f.files["/root/report.txt"].reads == 3
    # a confirmed write anywhere bumps the mutation clock → next read is fresh
    f.observe_output("echo 'new' > /root/report.txt", "", 0)
    f.observe_output("cat /root/report.txt", "SERVICES=y", 0)
    assert f.files["/root/report.txt"].reads == 1
    # and a run of the producer script also refreshes the budget
    f.observe_output("cat /root/report.txt", "SERVICES=y", 0)
    f.observe_output("cat /root/report.txt", "SERVICES=y", 0)
    assert f.files["/root/report.txt"].reads == 3
    f.observe_output("/root/report.sh", "done", 0)
    f.observe_output("cat /root/report.txt", "SERVICES=z", 0)
    assert f.files["/root/report.txt"].reads == 1


def test_failed_read_does_not_settle_file():
    """s72: ssh -J hang returned a prompt fragment for 'cat /root/db.txt' —
    three identical FAILURE outputs counted as settled content and the
    4th read was denied though the file was never seen. Only code==0
    counts as a read."""
    from coach.facts import FactsDB, file_key
    f = FactsDB()
    rkey = file_key("ssh -J a@b c@d 'cat /root/db.txt'", "/root/db.txt")
    for _ in range(4):
        f.observe_output("ssh -J a@b c@d 'cat /root/db.txt'",
                         "(root@kali)-[/]# sshpass", None)
    assert f.files.get(rkey) is None or f.files[rkey].reads == 0
    f.observe_output("cat /root/db.txt", "flag{abc}", 0)
    assert f.files["/root/db.txt"].reads == 1
    # nonzero exit (sudo denied, ssh refused) also yields no content
    f.observe_output("sudo cat /root/db.txt", "Sorry, user x", 1)
    assert f.files["/root/db.txt"].reads == 1


def test_topn_count_becomes_finding():
    """s54: '     5 203.0.113.44' from uniq -c is top-talker evidence — it
    must persist as a finding, not vanish with the context window."""
    from coach.facts import FactsDB
    f = FactsDB()
    f.observe_output(
        "ssh soc@audit01 'grep \"Failed password\" /var/log/auth.log | "
        "grep -oP \"from \\K[0-9.]+\" | sort | uniq -c | sort -rn'",
        "      5 203.0.113.44\n      4 192.0.2.99", 0)
    assert "top:5x203.0.113.44" in f.findings
    # non-count output doesn't fire
    f2 = FactsDB()
    f2.observe_output("id", "uid=0(root)", 0)
    assert not any(t.startswith("top:") for t in f2.findings)


def test_file_key_host_attribution():
    from coach.facts import FactsDB, file_key
    assert file_key("sshpass -p 'x' ssh deploy@shop01 'cat /tmp/f'",
                    "/tmp/f") == "/tmp/f@shop01"
    assert file_key("cat /tmp/f", "/tmp/f") == "/tmp/f"
    f = FactsDB()
    # same path on two hosts = two distinct facts
    f.observe_output("ssh deploy@shop01 'cat /tmp/f'", "a", 0)
    f.observe_output("cat /tmp/f", "b", 0)
    assert f.files["/tmp/f@shop01"].reads == 1
    assert f.files["/tmp/f"].reads == 1
    # renders with the @host suffix — the model sees where the file lives
    assert "/tmp/f@shop01" in f.render(2000)


def test_loot_digest_on_secret_yielding_read():
    from coach.facts import FactsDB
    f = FactsDB()
    f.observe_output("cat /tmp/config.env",
                     "DEPLOY_PASS=pw123\nAPI_TOKEN=tok-9\nAPI_URL=http://10.0.0.4:9000", 0)
    assert any(f.startswith("loot:config.env→") for f in f.findings)
    tag = next(f for f in f.findings if f.startswith("loot:"))
    assert "API_TOKEN" in tag or "DEPLOY_PASS" in tag
    # second read doesn't duplicate the digest
    f.observe_output("cat /tmp/config.env",
                     "DEPLOY_PASS=pw123\nAPI_TOKEN=tok-9", 0)
    assert sum(1 for f in f.findings
               if f.startswith("loot:config.env")) == 1


def test_valid_on_marks_working_credential():
    from coach.facts import FactsDB
    f = FactsDB()
    f.observe_output(
        "sshpass -p 'Nordm#arkt!25' ssh deploy@shop01 'whoami'",
        "deploy", 0)
    c = next(c for c in f.creds if c.secret == "Nordm#arkt!25")
    assert "shop01" in c.valid_on and "shop01" in c.tested_on
    # mysql cred inside a wrapped command attributes to the -h host, not
    # the ssh pivot — the bug that hid DB tests behind the wrong host
    f2 = FactsDB()
    f2.observe_output(
        "sshpass -p 'X' ssh deploy@shop01 "
        "'mysql -h 172.20.1.3 -u root -pGood -e \"select 1\"'", "1", 0)
    mc = next(c for c in f2.creds if c.user == "root")
    assert "172.20.1.3" in mc.valid_on
    # exit 0 but auth-fail output → NOT valid
    f3 = FactsDB()
    f3.observe_output(
        "sshpass -p 'X' ssh deploy@shop01 'mysql -h db -u u -pBad'",
        "Access denied for user 'u'@'db'", 0)
    c3 = next(c for c in f3.creds if c.secret == "Bad")
    assert not c3.valid_on


def test_read_target_ignores_url_paths():
    """curl|head must not count http://host:port/… as a file read —
    live s46 false-positive blocked API curls as 'read /172.20.1.2'."""
    from coach.facts import FactsDB, read_target
    assert read_target(
        "curl -s http://172.20.1.2:8080/ 2>&1 | head -50") is None
    assert read_target(
        "curl -s http://172.20.1.2:8080/api/export?format=json") is None
    # curl itself never counts (not a read cmd) — identical URL fetches
    # are caught by the _out_sigs dedup, not the file-read guard
    assert read_target(
        "curl -s 'http://h:8080/export?path=/etc/passwd'") is None
    # real reads unaffected
    assert read_target("cat /tmp/x | head") == "/tmp/x"
    assert read_target(
        "sshpass -p x ssh u@h 'cat /var/log/y'") == "/var/log/y"
    f = FactsDB()
    f.observe_output(
        "curl -s http://172.20.1.2:8080/api 2>&1 | head -50", "{}", 0)
    assert not any(p.startswith("/172.20.1.2") for p in f.files)


def test_read_target_ignores_redirects_and_cd_prefix():
    """s46: `2>/dev/null` was counted 11x as a read (it out-lengthed real
    paths) and `cd /tmp && …|head` counted /tmp. A path only counts when
    it sits in the same segment as the read command."""
    from coach.facts import read_target
    assert read_target("cat /tmp/x 2>/dev/null") == "/tmp/x"
    assert read_target("ls /tmp 2>/dev/null") == "/tmp"          # real read
    assert read_target("cd /tmp && find x -type f | head -20") is None
    assert read_target("ls /var 2>/dev/null | head") == "/var"
    # pipe targets of a second read-command DO count (grep reads /b)
    assert read_target("cat /a | grep p /b") in ("/a", "/b")
    assert read_target("cat /f 2>&1 | head -5") == "/f"
    # writes still excluded
    assert read_target("cat > /tmp/out.txt") is None
    assert read_target("echo hi > /dev/null") is None
    # unchanged single-segment behaviour
    assert read_target("cat /etc/passwd") == "/etc/passwd"


def test_caps_promotion_and_render():
    """A root-cron path only becomes a cap once the file carries OUR write —
    seeing a schedule ≠ having proven code-exec."""
    from coach.facts import FactsDB
    f = FactsDB()
    # schedule discovered but never written → no cap
    f.observe_output("ssh u@h 'cat /etc/cron.d/shop-backup'",
                     "*/2 * * * * root /opt/shop/backup.sh", 0)
    assert not f.caps
    # we write a payload into that file, then see the schedule again → cap
    f.observe_output("ssh u@h \"echo 'cp /root/flag /tmp/x' >> "
                     "/opt/shop/backup.sh\"", "", 0)
    f.observe_output("ssh u@h 'cat /etc/cron.d/shop-backup'",
                     "*/2 * * * * root /opt/shop/backup.sh", 0)
    assert "root-exec via /opt/shop/backup.sh@h" in f.caps
    # caps render even in compact mode (highest-value line)
    out = f.render(max_chars=200)
    assert "caps:" in out and "root-exec" in out


def test_unreachable_facts():
    """s46: direct curls to the docker-internal API retried every restart —
    timeout/unreachable must become a persistent denial fact."""
    from coach.facts import FactsDB
    f = FactsDB()
    # curl exit 28, empty output — the unreachable signal
    f.observe_output("curl -s --max-time 15 http://172.20.1.2:8080/", "", 28)
    assert "unreachable:172.20.1.2@kali" in f.denials
    # via ssh pivot — vantage is the pivot, target is the other IP
    f.observe_output(
        "ssh deploy@shop01 'curl -s --max-time 15 http://172.20.1.2:8080/'",
        "", 28)
    assert "unreachable:172.20.1.2@shop01" in f.denials
    # refused (exit 7) is NOT unreachable — the host answered
    f.observe_output("curl -s http://172.20.1.9:99/", "", 7)
    assert not any("172.20.1.9" in d for d in f.denials)


def test_caps_direct_and_bound():
    from coach.facts import FactsDB
    f = FactsDB()
    f.apply_delta({"caps": ["mysql-file:shop_ro", "root-shell@shop01",
                            "mysql-file:shop_ro"]})
    assert f.caps == ["mysql-file:shop_ro", "root-shell@shop01"]  # dedup
    f.apply_delta({"caps": [f"c{i}" for i in range(8)]})
    assert len(f.caps) <= 6                                       # bounded


def test_normalize_plan_edges():
    from coach.state import normalize_plan
    # bare strings → todo; status aliases; caps
    items = normalize_plan(
        ["first", {"t": "second", "s": "WIP"}, {"t": "x", "s": "weird"},
         {"t": "done-thing", "s": "finished"}, {"text": "alt key"},
         42, {"t": ""}] + [{"t": f"s{i}"} for i in range(20)])
    assert items[0] == {"t": "first", "s": "todo"}
    assert items[1]["s"] == "doing"          # WIP alias
    assert items[2]["s"] == "todo"           # unknown → todo
    assert items[3]["s"] == "done"           # finished alias
    assert items[4]["t"] == "alt key"        # text/step fallback keys
    assert len(items) == 10                  # PLAN_MAX_ITEMS
    assert all(i["t"] for i in items)
    # long text is cut, not dropped
    long = normalize_plan([{"t": "x" * 200}])
    assert len(long[0]["t"]) == 110


def test_routing_tunnel_drops_stale_kali_reachability_denials():
    """sshuttle/vpn changes kali's L3 vantage — pre-tunnel filtered:/
    unreachable: @kali facts go stale and must be dropped or they keep
    bricking connects that now work (s84: sshuttle up, direct ssh to
    'filtered' app01 succeeded — only a lucky restart had cleared it)."""
    f = FactsDB()
    f.denials += ["filtered:10.1.10.32@kali", "unreachable:10.9.9.9@kali",
                  "missing:sshpass@web01", "filtered:10.1.10.32@web01",
                  "denied:sudo@web01"]
    f.observe_output("sshuttle -r deploy@web01 10.1.10.0/24", "", 0)
    # kali-scoped reachability dead-ends are gone — the tunnel rerouted
    assert "filtered:10.1.10.32@kali" not in f.denials
    assert "unreachable:10.9.9.9@kali" not in f.denials
    # host-scoped + non-reachability facts are vantage-correct — untouched
    assert "missing:sshpass@web01" in f.denials
    assert "filtered:10.1.10.32@web01" in f.denials
    assert "denied:sudo@web01" in f.denials


def test_socks_forward_and_failed_setup_keep_denials():
    """ssh -D only helps proxy-aware tools (direct connects stay local),
    and a FAILED tunnel attempt proves nothing — denials must survive."""
    f = FactsDB()
    f.denials.append("filtered:10.1.10.32@kali")
    f.observe_output("ssh -D 9050 -fN deploy@web01", "", 0)
    assert "filtered:10.1.10.32@kali" in f.denials          # no L3 change
    f.observe_output("sshuttle -r deploy@web01 10.1.10.0/24",
                     "client: Connected.", 1)
    assert "filtered:10.1.10.32@kali" in f.denials          # failed = stale


def test_uid0_and_docker_exec_pin_proven_caps():
    """s57: root+container primitives were re-derived instead of re-used —
    a confirmed uid=0 / working docker exec must pin to caps (renders every
    turn)."""
    from coach.facts import FactsDB
    f = FactsDB()
    f.observe_output("sshpass -p x ssh deploy@shop01 id",
                     "uid=0(root) gid=0(root) groups=0(root)", 0)
    f.observe_output("ssh deploy@shop01 docker exec api cat /x", "DATA", 0)
    assert any("root-shell@shop01" in c for c in f.caps)
    assert any("docker exec api@shop01" in c for c in f.caps)
    # non-root uid and failing exec pin nothing
    f2 = FactsDB()
    f2.observe_output("ssh deploy@h id", "uid=1000(deploy) gid=1000(deploy)", 0)
    f2.observe_output("ssh deploy@h docker exec api cat /x", "err", 1)
    assert not f2.caps
