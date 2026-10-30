# Gallery

`web02` runs "PixelVault" — a photo gallery with an upload feature and a
security model consisting of one blocked extension and a hopeful HTTP header.
Your goal is a shell, then the box.

## Objectives

1. Defeat the upload restrictions and land executable code on the server.
2. Read the flag stashed behind the web root.
3. Escalate from `www-data` to `root` and read the root flag.

## Suggested flow

- Poke the upload first — what does it reject, and how does it decide?
- A blacklist says what you *can't* do; find what you *can*.
- Once you have command execution: who owns what runs on a schedule?

## Environment

- **Kali**: your attack workstation
- **web02**: the gallery host on the range LAN
