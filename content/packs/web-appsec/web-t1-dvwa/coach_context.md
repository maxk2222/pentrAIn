Quest: web-t1-dvwa (tier 1, web-appsec)

Ground truth:
- DVWA on dvwa01 port 80, creds admin/password, security level 'low' intended
- flag1: file /flags/flag1.txt inside the dvwa container — reachable via
  /vulnerabilities/fi/?page=../../../../flags/flag1.txt
- flag2 (command kind): any *.php in /var/www/html/hackable/uploads —
  the state check runs `docker exec dvwa ls …/uploads/*.php | head -1`
  on the host vm. The platform auto-verifies when the user clicks "Check".

Style: beginner web — explain *why* file inclusion works (the app includes
whatever `page=` says) rather than just the payload. If they're stuck, walk
through the upload flow step by step.
