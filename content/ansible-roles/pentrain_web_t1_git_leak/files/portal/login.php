<?php
require_once __DIR__ . '/config.php';
$msg = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $u = $_POST['user'] ?? '';
    $p = $_POST['pass'] ?? '';
    if ($u === $DB_USER && $p === $DB_PASS) {
        $msg = 'welcome back, ' . htmlspecialchars($u) . ' — nothing wired up yet';
    } else {
        $msg = 'invalid credentials';
    }
}
?>
<!doctype html>
<html>
<head><title>DevPortal — sign in</title></head>
<body>
  <h1>Sign in</h1>
  <form method="post">
    <label>User <input name="user"></label><br>
    <label>Pass <input name="pass" type="password"></label><br>
    <button type="submit">Login</button>
  </form>
  <p><?= htmlspecialchars($msg) ?></p>
</body>
</html>
