# Nonce Grinder

**Situation.** A contractor built a "secure" challenge API on `api01:8080`:
fetch a nonce, prove you know a 4-digit PIN, receive a bearer token, read
the secret. The PIN space is tiny — the endpoint is practically begging to
be brute-forced, but rate limits and expiring nonces mean you can't do it
by hand.

**Your job**

Write `/root/solve.py` on your Kali — a Python script that:

1. Discovers the API (`/api/health`, `/api/nonce`)
2. Brute-forces the PIN: fetch nonce → compute the documented proof → POST
   → repeat until a token comes back
3. Uses the token to pull `/api/secret` and saves what it returns to
   `/root/loot.txt`
4. Submit the secret itself as a flag.

**Rules of engagement.** The nonce is single-use and expires after two
minutes — no replaying. The token lives five minutes — plenty for a script,
hopeless by hand. That's the point.

Difficulty: medium · Track: Scripting & Automation
