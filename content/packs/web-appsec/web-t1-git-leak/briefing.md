# Committed

`web01` hosts "DevPortal" — an internal tool someone shipped by copying the
whole project directory to the web root. *The whole directory.* The deploy
credentials were supposedly rotated out of the code. Verify that claim.

## Objectives

1. Map the site — what's reachable that shouldn't be?
2. Recover the application's source and find what the history remembers.
3. Reach the restricted area.
4. Turn leaked credentials into a shell, then the user flag.

## Suggested flow

- Directory-bust the web root — some directories should never go to production.
- PHP executes server-side; fetching `config.php` over HTTP won't help. The
  repository, on the other hand, is just files.
- Rebuild the working tree and read the commit history — secrets tend to
  stay in history even after they're "removed".

## Environment

- **Kali**: your attack workstation
- **web01**: the DevPortal host on the range LAN
