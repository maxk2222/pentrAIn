<!doctype html>
<html>
<head><title>PixelVault — your private gallery</title></head>
<body>
  <h1>PixelVault</h1>
  <p>Upload your photos. <em>Only image files are accepted — we check!</em></p>
  <form action="upload.php" method="post" enctype="multipart/form-data">
    <input type="file" name="photo">
    <button type="submit">Upload</button>
  </form>
  <h2>Your uploads</h2>
  <ul>
  <?php
    foreach (glob(__DIR__ . '/uploads/*') as $f) {
        $b = basename($f);
        echo "<li><a href=\"/uploads/" . rawurlencode($b) . "\">" . htmlspecialchars($b) . "</a></li>";
    }
  ?>
  </ul>
</body>
</html>
