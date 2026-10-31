# Defense notes — No Client Needed

## What PMKID taught

- **PMKID harvesting needs no victim.** The AP hands out a hashable
  structure to *anyone who asks* — no client present, no deauth, nothing
  to see on the air except one quiet request. hostapd's `pmkid` option
  (and many enterprise AP defaults) makes secure-net vulnerable even while
  "empty." Disabling PMKID caching where not needed, plus WPA3-SAE (which
  eliminates the PMKID oracle entirely), closes it.
- **"Hardened" ≠ verified.** secure-net's owners believed it strong
  because WPA2 was enabled — but a config option re-opened the offline
  path. Hardening claims need validation by attack, not by checklist.
- **Rogue APs are a land-use violation.** `free-wifi` was an open AP
  squatting on the organization's spectrum — whether planted maliciously
  or just someone's travel router, clients that join it hand their traffic
  to an unknown operator. Site surveys and WIPS exist to catch exactly this.

## Detection opportunities

- **WIDS/WIPS**: unknown BSSIDs, open encryption near secured networks,
  PMKID request patterns (hcxdumptool's probe behavior is distinctive).
- **Client telemetry**: corporate devices joining unauthorized SSIDs —
  the free-wifi association is logged somewhere if you look.
- **Config audit**: `pmkid`/`okc` options in AP configs, unauthorized
  radios on network segments.

## Takeaway

The quietest wireless attack is the one that never touches a client —
if your AP answers strangers with crackable material, the handshake
already happened.
