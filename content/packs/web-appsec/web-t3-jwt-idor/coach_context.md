Quest: web-t3-jwt-idor (tier 3, web-appsec)

Ground truth for the coach:
- flask api on jwt01:80, systemd unit pentrain-jwt-api runs as root
- POST /api/login auditor/Audit2024! (also intern/Intern2024!) → HS256 JWT
- JWT_SECRET = "letmein" — jwt_tool -C / hashcat -m 16500
- IDOR: GET /api/users/1/export with ANY valid token → admin's export
  serves /var/lib/api/user-flag.txt (user-flag)
- forge {"sub":"admin","uid":1,"admin":true} with the cracked secret →
  GET /api/admin/report → /var/lib/api/admin-flag.txt (admin-flag)

Intended path:
index (demo creds) → login → decode JWT → IDOR uid 1 → crack secret →
forge admin:true → admin report

Common wrong turns:
- alg:none attacks (PyJWT requires the signature — crack instead)
- fuzzing uids forever (1 is the target; 2/3 return no export)
- forging admin but calling the IDOR endpoint (admin gate is on
  /api/admin/report)
- trying to crack the JWT signature offline with -m 13100 (that's
  kerberos; JWT is 16500)

Style: tier 3 teaching — same primitives as web-t3-exam but friendlier
surface. Let them drive; push jwt_tool only after manual decoding.
