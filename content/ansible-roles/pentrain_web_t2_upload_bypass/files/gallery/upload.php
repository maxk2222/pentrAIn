<?php
// "secure" upload — blocks .php. What could go wrong?
$target = __DIR__ . '/uploads/';
$msg = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_FILES['photo'])) {
    $name = basename($_FILES['photo']['name']);
    $ext  = strtolower(pathinfo($name, PATHINFO_EXTENSION));
    $type = $_FILES['photo']['type'] ?? '';

    $blacklist = ['php', 'php3', 'php4', 'php5', 'php7', 'pht'];
    if (in_array($ext, $blacklist, true)) {
        $msg = "rejected: '.$ext' files are not allowed";
    } elseif (!str_starts_with($type, 'image/')) {
        $msg = "rejected: content-type '$type' is not an image";
    } elseif (move_uploaded_file($_FILES['photo']['tmp_name'], $target . $name)) {
        $msg = "uploaded: <a href='/uploads/" . rawurlencode($name) . "'>" .
               htmlspecialchars($name) . "</a>";
    } else {
        $msg = 'upload failed';
    }
}
?>
<!doctype html>
<html><body>
  <p><?= $msg ?></p>
  <p><a href="/">back</a></p>
</body></html>
