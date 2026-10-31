# Defense notes — Zero-Touch Vault

## Injection → pivot, reconstructed

- **Unquoted shell interpolation.** `ping -c1 "$Q"` takes CGI input
  straight into a shell — any metacharacter is an execution. The fix
  isn't escaping (always incomplete) but removing the shell: run the tool
  with an argv array (`subprocess.run(["ping","-c1",host])`, `execve` —
  never `system()`/`bash -c` on user input), and validate `host` as an IP
  literal first.
- **Credential spill on the edge.** The vault password lived in a
  world-readable note on the *most exposed* box — exactly the host least
  able to protect it. Edge systems should hold zero downstream secrets;
  a vault that trusts the edge must assume the edge's compromise.
- **Chokepoint without telemetry.** db01's "only from web01" rule is good
  segmentation — but nobody logged web01's outbound SSH. The injection
  that reached db01 was invisible to both hosts' defenders.

## Detection opportunities

- CGI access log anomalies: `host=` values containing `;`, `$`, backticks.
- www-data spawning `ssh`/`sshpass` — process lineage alerts (auditd:
  `ssh` with PPID=apache is a smoking gun).
- New files in service homes (`/home/vaultadm/.pwned`) — file-integrity
  monitoring catches post-exploit markers.

## Takeaway

Every layer here was individually plausible — together they scripted the
breach. Defense-in-depth means any *single* layer must not be load-bearing.
