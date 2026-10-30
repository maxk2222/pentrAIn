Quest: web-t2-juice-shop (tier 2, web-appsec)

Ground truth:
- Juice Shop on juice01:3000 (container `juice-shop`)
- flag1: file /juice-shop/ftp/flag1.txt → reachable at http://juice01:3000/ftp/flag1.txt
- flag2 (command kind): the platform curls /api/Challenges on the host and
  checks the adminSection challenge is solved. Solved by viewing
  /#/administration while logged in. Login bypass: POST /rest/user/login
  with email `' OR 1=1--` and any password.
- score board lives at /#/score-board (not linked — recon pays off).

Style: real exploitation — let them drive the technique. If they burn time on
the SQLi syntax, remind them the bypass must be POSTed as JSON, not typed in
the form (browser escapes differ). The ftp flag is a free win — reward it.
