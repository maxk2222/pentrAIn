# Defense notes — DVWA

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Unsanitized `include($_GET['page'])` | LFI reads arbitrary files (`/flags/flag1.txt`) | Never include user-controlled paths; whitelist allowed pages |
| Unrestricted file upload | `.php` webshell executes under the web server | Validate type+extension, store outside docroot, `deny` execution of upload dir |
| Default credentials | `admin/password` | Force password change on first login |
| Container + host co-residency | Compromise of app reaches the docker host | Separate hosts, least-privilege container user, read-only rootfs |

## Hardening

```php
// include only from a whitelist — never the raw request
$allowed = ['home.php','about.php'];
$page = in_array($_GET['page'], $allowed) ? $_GET['page'] : 'home.php';
include $page;

// uploads: store outside docroot, random name, no execution
$dst = '/var/uploads/' . bin2hex(random_bytes(8));
move_uploaded_file($_FILES['f']['tmp_name'], $dst);
```

```nginx
# nginx: never execute php in the upload tree
location ^~ /hackable/uploads/ {
    location ~ \.php$ { deny all; }
}
```

## Detection

- WAF/ModSecurity rules for `../` in `page=` parameters
- Alert on new files in upload dirs matching `*.php`, `*.phtml`
- Container runtime monitoring (Falco) for `sh`/`bash` children of the web process

## Further reading

- OWASP Top 10: A01 Broken Access Control (path traversal), A05 Security Misconfiguration
- DVWA source: https://github.com/digininja/DVWA
