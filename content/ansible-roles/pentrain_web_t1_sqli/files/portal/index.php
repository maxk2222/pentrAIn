<?php
// employee portal — web-t1-sqli-login teaching app. Deliberately vulnerable:
// raw-string SQL for the lesson web-t1-exam grades on.
session_start();
$db = new SQLite3('/var/lib/portal-data/portal.db');
$msg = '';
$flag = null;
$rows = [];

if (isset($_GET['logout'])) { session_destroy(); header('Location: /'); exit; }

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $u = $_POST['username'] ?? '';
    $p = $_POST['password'] ?? '';
    // vulnerable: string interpolation straight into the query
    $q = "SELECT id, username FROM users WHERE username='$u' AND password='$p'";
    $res = @$db->query($q);
    if ($res) {
        while ($r = $res->fetchArray(SQLITE3_ASSOC)) { $rows[] = $r; }
    }
    if ($rows) {
        $_SESSION['user'] = $rows[0]['username'];
        header('Location: /');
        exit;
    }
    $msg = 'invalid credentials';
}

if (isset($_SESSION['user'])) {
    $flag = @file_get_contents('/var/lib/portal-data/flag.txt');
}
?>
<!doctype html><html><head><meta charset="utf-8"><title>Employee Portal</title>
<style>
body{font-family:system-ui;background:#0f1420;color:#dde;max-width:520px;margin:8vh auto}
.panel{background:#1a2132;border:1px solid #2a3550;border-radius:10px;padding:28px}
input{display:block;width:100%;margin:8px 0;padding:10px;border-radius:6px;border:1px solid #39466b;background:#10172a;color:#dde}
button{padding:10px 20px;border:0;border-radius:6px;background:#3b82f6;color:#fff;cursor:pointer}
.err{color:#f87171;margin:10px 0}.flag{background:#0d3b2e;border:1px solid #10b981;padding:14px;border-radius:6px;margin-top:16px;font-family:monospace}
a{color:#7aa2ff}
</style></head><body>
<div class="panel">
<?php if ($flag !== null): ?>
<h2>Welcome back, <?= htmlspecialchars($_SESSION['user']) ?></h2>
<p>Internal memo flag:</p>
<div class="flag"><?= htmlspecialchars($flag) ?></div>
<p><a href="/?logout=1">log out</a></p>
<?php else: ?>
<h2>Employee Portal — sign in</h2>
<?php if ($msg): ?><div class="err"><?= htmlspecialchars($msg) ?></div><?php endif; ?>
<form method="post">
<input name="username" placeholder="username" autofocus>
<input name="password" type="password" placeholder="password">
<button>sign in</button>
</form>
<p style="opacity:.5;font-size:.85em">v0.9 — IT is still testing</p>
<?php endif; ?>
</div></body></html>
