-- nordmarkt shop db — the migration leftovers are the finding:
-- shop_ro holds SELECT + FILE (global priv) so LOAD_FILE still works.
CREATE DATABASE IF NOT EXISTS shop;
CREATE USER IF NOT EXISTS 'shop_ro'@'%' IDENTIFIED BY 'Rd0nly!Nm25';
GRANT SELECT ON shop.* TO 'shop_ro'@'%';
GRANT FILE ON *.* TO 'shop_ro'@'%';
FLUSH PRIVILEGES;

USE shop;
CREATE TABLE IF NOT EXISTS vault (
    id INT PRIMARY KEY AUTO_INCREMENT,
    item VARCHAR(80) NOT NULL,
    note VARCHAR(255) NOT NULL
);
INSERT INTO vault (item, note) VALUES
  ('archive-path', 'old secret store dumped to /srv/loot/flag.txt by the migration — never cleaned up'),
  ('order-2024-011', 'feinkost-box altes land x40 — reorder when stock < 10'),
  ('order-2024-014', 'sommertracht honig 500g x120 for the summer run'),
  ('todo-nm-88', 'lock down FILE priv on shop_ro — migration leftover, fix after season');
