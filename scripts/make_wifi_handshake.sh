#!/bin/bash
# make_wifi_handshake.sh — generate a real WPA handshake capture for the
# wifi track's offline-cracking quests.
#
# Run on a Linux host with wifi tooling (hostapd, aircrack-ng, iw,
# wpa_supplicant) and the mac80211_hwsim kernel module — the PVE host or any
# Debian/Kali box works. Assumes the host has NO physical wireless NICs
# (the first three wlan* interfaces must be the hwsim radios). Usage:
#
#   sudo ./make_wifi_handshake.sh [ssid] [passphrase] [outfile.cap]
#
# Produces an airodump .cap containing a captured 4-way handshake between
# a hostapd AP (first radio) and a wpa_supplicant client (third radio);
# airodump monitors on the second. Verified by aircrack before success.
set -euo pipefail
SSID="${1:-labnet}"
PSK="${2:-coffee123}"
OUT="${3:-handshake.cap}"

for t in hostapd airodump-ng aireplay-ng aircrack-ng wpa_supplicant iw; do
    command -v "$t" >/dev/null || { echo "missing: $t"; exit 1; }
done
[[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }

# Precise -x process names only — a regex/pkill -f can match this script's
# own cmdline and self-kill the shell.
cleanup() {
    set +e
    [[ -n "${DUMP:-}" ]] && kill "$DUMP" 2>/dev/null
    pkill -x airodump-ng 2>/dev/null
    pkill -x wpa_supplicant 2>/dev/null
    pkill -x hostapd 2>/dev/null
}
trap cleanup EXIT
cleanup                      # leftovers from previous runs
rm -f /tmp/labcap-*.cap /tmp/hs.conf /tmp/sup.conf

CAPDIR=$(mktemp -d)

# Ensure 3 hwsim radios; if already loaded with another count, reload.
modprobe mac80211_hwsim radios=3 2>/dev/null || true
sleep 1
mapfile -t WLANS < <(iw dev 2>/dev/null | awk '$1=="Interface"{print $2}' | sort)
if [[ ${#WLANS[@]} -lt 3 ]]; then
    modprobe -r mac80211_hwsim 2>/dev/null || true
    sleep 1
    modprobe mac80211_hwsim radios=3
    sleep 1
    mapfile -t WLANS < <(iw dev | awk '$1=="Interface"{print $2}' | sort)
fi
[[ ${#WLANS[@]} -ge 3 ]] || { echo "[!] need 3 hwsim radios, found: ${WLANS[*]:-none}"; exit 1; }
AP_IF="${WLANS[0]}"; MON_IF="${WLANS[1]}"; STA_IF="${WLANS[2]}"
echo "[*] radios: ap=${AP_IF} mon=${MON_IF} sta=${STA_IF}"
rfkill unblock all 2>/dev/null || true
ip link set "$AP_IF" up; ip link set "$STA_IF" up

cat > /tmp/hs.conf <<EOF
interface=${AP_IF}
ssid=${SSID}
hw_mode=g
channel=6
wpa=2
wpa_passphrase=${PSK}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

hostapd -B /tmp/hs.conf
sleep 2
BSSID=$(iw "$AP_IF" info | awk '/addr/{print $2}')
[[ -n "$BSSID" ]] || { echo "[!] no BSSID on ${AP_IF}"; exit 1; }
echo "[*] AP '${SSID}' up at ${BSSID}"

airodump-ng --bssid "${BSSID}" -c 6 -w "${CAPDIR}/cap" "$MON_IF" >/dev/null 2>&1 &
DUMP=$!
sleep 3

printf 'network={\n ssid="%s"\n psk="%s"\n}\n' "${SSID}" "${PSK}" > /tmp/sup.conf
wpa_supplicant -B -i "$STA_IF" -c /tmp/sup.conf

for i in 1 2 3; do
    sleep 6
    aireplay-ng -0 3 -a "${BSSID}" "$MON_IF" >/dev/null 2>&1 || true
    CAP=$(ls -t "${CAPDIR}"/cap-*.cap 2>/dev/null | head -1 || true)
    [[ -n "${CAP}" ]] && aircrack-ng "$CAP" 2>/dev/null | grep -q "handshake" && break
    echo "[*] attempt $i — waiting for handshake"
done

kill "$DUMP" 2>/dev/null || true
wait "$DUMP" 2>/dev/null || true
CAP=$(ls -t "${CAPDIR}"/cap-*.cap 2>/dev/null | head -1 || true)
[[ -n "${CAP}" ]] || { echo "[!] no capture file produced"; exit 1; }

CHECK=$(aircrack-ng "$CAP" 2>/dev/null)
echo "$CHECK" | grep -q "handshake" || { echo "[!] no handshake captured — rerun"; exit 1; }
echo "$CHECK" | grep -qi "$SSID" || { echo "[!] capture holds a different SSID — stale file?"; exit 1; }

mv "$CAP" "$OUT"
rm -rf "$CAPDIR" /tmp/labcap-* /tmp/hs.conf /tmp/sup.conf
echo "[+] wrote $OUT — verified handshake for '${SSID}'"
