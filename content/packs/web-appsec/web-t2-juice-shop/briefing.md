# Juice Heist

An OWASP Juice Shop instance runs on `juice01:3000`. Two flags test two
different disciplines: anonymous information disclosure, and actually solving
a real challenge inside the app.

## Objectives

1. Recon the app — find the hidden score board (`/#/score-board`).
2. Flag 1: the `/ftp` directory is world-readable — one of our flags sits inside.
3. Flag 2: solve the *adminSection* challenge — the platform verifies it
   automatically via the app's own API.

## Notes

- The ftp flag is unauthenticated — easy points if you find the dir.
- adminSection requires being *any* logged-in user. The login form is injectable.
- Everything else in the shop is bonus practice — the challenge catalog is huge.
