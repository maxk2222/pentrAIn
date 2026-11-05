# Free Lab — defender notes

This environment is intentionally undefended: the Free Lab exists so the
operator can work on any authorized target without a range or objectives.

## What to know

- The Kali VM is disposable. If you break it, reset the session — the
  template rebuilds.
- The WAN uplink is real egress. Anything you install or run leaves the
  lab boundary like any host on your network.
- There are no lab-side targets to defend, and no flags to protect.

## Rules that still apply

- Only point the tooling at systems you are authorized to test. The
  coach's ROE guards are off in this mode — authorization is on you.
- Host-destructive commands (disk wipes, fork bombs, reboot/shutdown of
  the lab host) are still blocked for safety.
