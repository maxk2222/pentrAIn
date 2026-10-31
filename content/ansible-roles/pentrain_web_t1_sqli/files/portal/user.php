<?php
// employee "who is" lookup — second injection point: the result is RENDERED,
// which is what makes UNION extraction possible.
$db = new SQLite3('/var/lib/portal-data/portal.db');
$out = [];
$u = $_GET['u'] ?? '';
if ($u !== '') {
    // vulnerable: raw interpolation, results echoed back — the UNION sink
    $q = "SELECT username, notes FROM users WHERE username='$u'";
    $res = @$db->query($q);
    if ($res) {
        while ($r = $res->fetchArray(SQLITE3_ASSOC)) { $out[] = $r; }
    }
    if (!$out) { $out[] = ['username' => '(no match)', 'notes' => '']; }
}
?>
<!doctype html><html><head><meta charset="utf-8"><title>Who is…</title>
<style>body{font-family:system-ui;background:#0f1420;color:#dde;max-width:520px;margin:8vh auto}
.panel{background:#1a2132;border:1px solid #2a3550;border-radius:10px;padding:28px}
td{padding:6px 12px;border-bottom:1px solid #2a3550;font-family:monospace}
a{color:#7aa2ff}</style></head><body>
<div class="panel"><h2>Directory lookup</h2>
<form><input name="u" placeholder="exact username" value="<?= htmlspecialchars($u) ?>">
<button>search</button></form>
<?php if ($out): ?><table>
<?php foreach ($out as $r): ?>
<tr><td><?= htmlspecialchars($r['username']) ?></td><td><?= htmlspecialchars($r['notes']) ?></td></tr>
<?php endforeach; ?></table><?php endif; ?>
<p><a href="/">← portal</a></p>
</div></body></html>
