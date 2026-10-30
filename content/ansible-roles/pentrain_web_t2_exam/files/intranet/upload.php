<?php
// document upload — "secured" by an extension blacklist (the T2 bug:
// blacklist misses .phtml/.phar and is case-sensitive).
session_start();
if (!isset($_SESSION['user'])) { header('Location: /'); exit; }

$msg = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_FILES['doc'])) {
    $name = $_FILES['doc']['name'];
    $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
    $banned = ['php', 'php3', 'php4', 'php5', 'php7', 'pht'];
    if (in_array($ext, $banned)) {
        $msg = 'blocked: executable extension';
    } else {
        $dest = '/var/www/html/uploads/' . basename($name);
        if (move_uploaded_file($_FILES['doc']['tmp_name'], $dest)) {
            $msg = 'uploaded → /uploads/' . htmlspecialchars(basename($name));
        } else {
            $msg = 'upload failed';
        }
    }
}
?>
<!doctype html><html><head><meta charset="utf-8"><title>Upload</title>
<style>body{font-family:system-ui;background:#10141f;color:#dde;max-width:520px;margin:10vh auto}
.panel{background:#1a2130;border:1px solid #2b3650;border-radius:10px;padding:26px}
button{padding:10px 18px;border:0;border-radius:6px;background:#6366f1;color:#fff;cursor:pointer}
.msg{margin:12px 0;color:#a5f3fc}a{color:#93a6ff}</style></head><body>
<div class="panel">
<h2>Document upload</h2>
<p>PDFs and office documents only — executable types are blocked.</p>
<?php if ($msg): ?><div class="msg"><?= $msg ?></div><?php endif; ?>
<form method="post" enctype="multipart/form-data">
<input type="file" name="doc">
<button>upload</button>
</form>
<p><a href="/">← back</a></p>
</div></body></html>
