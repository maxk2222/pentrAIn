<?php
// intranet t2-exam — login is string-interpolated SQL (bypassable), the
// admin area exposes an upload and reads the internal-report flag.
session_start();
$db = new SQLite3('/var/lib/intranet/app.db');
$msg = '';
$report = null;

if (isset($_GET['logout'])) { session_destroy(); header('Location: /'); exit; }

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $u = $_POST['username'] ?? '';
    $p = $_POST['password'] ?? '';
    $q = "SELECT id, username, role FROM users WHERE username='$u' AND password='$p'";
    $res = @$db->query($q);
    if ($res && $row = $res->fetchArray()) {
        $_SESSION['user'] = $row['username'];
        header('Location: /');
        exit;
    }
    $msg = 'invalid credentials';
}

if (isset($_SESSION['user'])) {
    $report = @file_get_contents('/var/lib/intranet/flag.txt');
}
?>
<!doctype html><html><head><meta charset="utf-8"><title>Intranet</title>
<style>
body{font-family:system-ui;background:#10141f;color:#dde;max-width:640px;margin:6vh auto}
.panel{background:#1a2130;border:1px solid #2b3650;border-radius:10px;padding:26px}
input{display:block;width:100%;margin:8px 0;padding:10px;border-radius:6px;border:1px solid #3a466b;background:#0f1524;color:#dde}
button{padding:10px 18px;border:0;border-radius:6px;background:#6366f1;color:#fff;cursor:pointer}
.err{color:#f87171}.flag{background:#12332a;border:1px solid #34d399;padding:14px;border-radius:6px;margin-top:14px;font-family:monospace}
a{color:#93a6ff}.nav{margin-top:18px;border-top:1px solid #2b3650;padding-top:14px}
</style></head><body>
<div class="panel">
<?php if ($report !== null): ?>
<h2>Intranet — <?= htmlspecialchars($_SESSION['user']) ?></h2>
<p>Quarterly internal report (restricted):</p>
<div class="flag"><?= htmlspecialchars($report) ?></div>
<div class="nav">
<p><a href="/upload.php">document upload</a> · <a href="/?logout=1">log out</a></p>
</div>
<?php else: ?>
<h2>Intranet — sign in</h2>
<?php if ($msg): ?><div class="err"><?= htmlspecialchars($msg) ?></div><?php endif; ?>
<form method="post">
<input name="username" placeholder="username" autofocus>
<input name="password" type="password" placeholder="password">
<button>sign in</button>
</form>
<p style="opacity:.45;font-size:.85em">corp intranet v2.2 — employees only</p>
<?php endif; ?>
</div></body></html>
