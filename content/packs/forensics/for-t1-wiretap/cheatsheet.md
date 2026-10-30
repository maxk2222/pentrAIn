# Cheatsheet — Wiretap

## Targets

- **pcap01** — victim host; `/evidence/` holds the span-port capture

## Useful commands

```bash
capinfos /evidence/capture.pcap           # what am I looking at?
tshark -r capture.pcap -q -z io,phs       # protocol hierarchy
tshark -r capture.pcap -Y 'ftp'           # control-channel commands
tshark -r capture.pcap -qz follow,tcp,ascii,0   # stream 0, readable
tcpdump -nn -r capture.pcap -A            # quick payload peek
strings capture.pcap | less               # last resort — loses structure
# GUI: wireshark → right-click a packet → Follow → TCP Stream
ssh <user>@<ip>
```

## Concepts

- FTP runs TWO channels: control (:21, the commands) and data (:20, the files)
- "Follow TCP Stream" reassembles a whole conversation — the single most
  useful wireshark move for triage
- Evidence files are signposts: what was transferred tells you where to look
  on the host
