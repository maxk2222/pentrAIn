# Pressing Matters

`wp01` runs the corporate intranet — WordPress, installed last quarter by a
marketing intern who has since moved on. Nobody changed the admin password.
Nobody ever does.

## Objectives

1. Enumerate the WordPress install — version, users, and what's lying in the
   uploads folder.
2. Get into `wp-admin`.
3. Turn admin access into code execution and collect the flag outside the
   web root.

## Suggested flow

- `wpscan` does the heavy lifting: enumerate users, plugins, themes, and the
  media library.
- One account matters. Common wordlists exist precisely for this.
- The Theme File Editor is a file-write primitive for PHP — use it.

## Environment

- **Kali**: your attack workstation
- **wp01**: the WordPress host on the range LAN
