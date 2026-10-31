# Defense — Signed & Confused

## What the API did wrong

- **Dictionary-word HS256 secret.** HS256 is symmetric — anyone who
  recovers the secret mints arbitrary claims. The crack took a wordlist.
- **IDOR / BOLA.** `/api/users/<id>/export` verified *a* token but never
  compared `claims["uid"]` to the requested id. Authentication is not
  authorization.
- **Trusting client-side claims.** `admin: true` came from the token —
  and the token came from whoever held the secret.

## How to fix it

- Long random secrets (or asymmetric RS256/EdDSA so verification keys
  can't sign); rotate and store them in a secret manager.
- Object-level authorization on every resource access — check the
  subject against the object owner, not just the signature.
- Privilege claims derived server-side; never trust role claims alone.

## Detection

- Access logs: sequential `/api/users/<id>` enumeration is IDOR-shaped.
- Token replay: `admin:true` appearing for accounts without the role,
  or `sub`/`uid` mismatches, signals a forged JWT.
- Failed-token volume + successful requests from one IP = cracking offline
  then testing — alert on 401→200 sequences.
