# Defense — No Preauth

## What the domain did wrong

- **Preauth disabled on a service account.** `DONT_REQUIRE_PREAUTH` means
  the KDC encrypts a ticket part with the account's password-derived key
  and hands it to anyone — offline cracking becomes a pure wordlist game.
- **A crackable password on top.** `L3gacy2024!` falls to rockyou-class
  wordlists in seconds; the primitive is only fatal because the password
  is weak.
- **Legacy exceptions documented in SYSVOL.** The runbook naming the
  account lived in a share every domain user can read.

## How to fix it

- Never set `DoesNotRequirePreAuth` — find and remediate it:
  `Get-ADUser -Filter {DoesNotRequirePreAuth -eq $true}`.
- If a legacy agent truly can't do preauth, rotate to a gMSA or a very
  long random password — the AS-REP then outlives any cracker.
- Audit SYSVOL for account names + operational notes.

## Detection

- Event 4768 with `Pre-Authentication Type: 0` = an AS-REP request that
  skipped preauth — the roast attempt itself.
- Burst of 4768s from one source across many accounts = spraying the
  technique domain-wide.
