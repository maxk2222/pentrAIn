# Defense — Blind Pipe

## What the CGI did wrong

- **Unquoted interpolation into `/bin/bash -c`.** `ping -c1 $Q` turns every
  metacharacter in `$Q` into shell syntax — `;`, `$( )`, backticks, pipes
  all execute.
- **No input validation.** An interface name is `[a-z0-9]+` at worst —
  the code accepted everything including whitespace and separators.
- **Command output echoed verbatim.** Whatever the injected command
  prints travels back in the response — built-in exfiltration.

## How to fix it

- Never build shell strings from user input — call the binary with an
  argv array (`subprocess.run(["ip","-brief","addr","show",name])` without
  `shell=True`).
- Validate against a strict allowlist (`^[a-z0-9.:-]{1,32}$`) *and* still
  avoid the shell.
- Return structured data, not raw command output.

## Detection

- Access logs: `%3B` (`;`), `%24%28` (`$(`), backticks, `&&`, `||` in
  query strings.
- Response-size anomalies: a status endpoint suddenly returning
  `/etc/passwd`-sized bodies.
- Egress: CGI workers have no business running `cat`, `curl`, `ssh` —
  audit child processes of the webserver.
