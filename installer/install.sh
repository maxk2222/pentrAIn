#!/usr/bin/env bash
# pentrAIn installer — wraps ansible-playbook with mode + safety flags.
# Live UI comes from plugins/callback/pentrain_ui.py (stdout_callback).
set -euo pipefail

cd "$(dirname "$0")"

MODE=""
DEDICATED=""
WITH_TEMPLATES="false"
ASSUME_YES=""
VERBOSE=""
EXTRA_ARGS=()

cy() { printf '\033[36m%s\033[0m\n' "$*"; }
gr() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
rd() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
yl() { printf '  \033[33m!\033[0m %s\n' "$*"; }

usage() {
  cat <<EOF
pentrAIn installer

  --mode nested|direct    required
                          nested = create engine VM on existing Proxmox (default home-server path)
                          direct = use an existing *dedicated* Proxmox host
  --i-know-dedicated      direct mode only, required when the host already has VMs
  --with-templates        also build the large Ludus templates (kali, debian, win2022) — multi-GB
  --yes, -y               skip the interactive confirmation prompt
  --verbose               raw ansible output instead of the live status board
  -h, --help              this help

Any other args are passed through to ansible-playbook (e.g. --check, -v, --tags).

Examples:
  ./install.sh --mode nested
  ./install.sh --mode direct --i-know-dedicated --with-templates --yes
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --i-know-dedicated) DEDICATED="true"; shift ;;
    --with-templates) WITH_TEMPLATES="true"; shift ;;
    --yes|-y) ASSUME_YES="true"; shift ;;
    --verbose) VERBOSE="true"; shift ;;
    -h|--help) usage ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

[[ -z "$MODE" ]] && { rd "--mode required"; usage; }
[[ "$MODE" != "nested" && "$MODE" != "direct" ]] && { rd "mode must be nested|direct"; usage; }

cy "┌──────────────────────────────────────────┐"
cy "│   pentrAIn · installer                   │"
cy "│   pentest training range                 │"
cy "└──────────────────────────────────────────┘"
echo

# ---------- preflight: fast local checks before ansible takes over ----------

command -v ansible-playbook >/dev/null || {
  rd "ansible not installed — apt install ansible, or pipx install ansible-core"; exit 1;
}
CORE_VER=$(ansible-playbook --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
CORE_MAJ=${CORE_VER%%.*}; CORE_MIN=${CORE_VER##*.}
if [[ -z "$CORE_VER" || "$CORE_MAJ" -lt 2 || ( "$CORE_MAJ" -eq 2 && "$CORE_MIN" -lt 15 ) ]]; then
  rd "ansible-core >= 2.15 required (found: ${CORE_VER:-unknown})"; exit 1;
fi
gr "ansible-core $CORE_VER"

[[ -f inventory.yml ]] || {
  rd "inventory.yml missing — cp inventory.example.yml inventory.yml and fill in your host"; exit 1;
}

# any existing pubkey type counts — don't create a redundant key pair
if ! { ls "$HOME"/.ssh/id_*.pub >/dev/null 2>&1 || ls /root/.ssh/id_*.pub >/dev/null 2>&1; }; then
  yl "no ssh key — generating one for VM cloud-init injection"
  mkdir -p "$HOME/.ssh"
  ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519" \
    && yl "set vm_ssh_pubkey in group_vars/all.yml to match the key on your PVE host" || true
fi

# mode → required inventory group, resolved through ansible-inventory itself
NEEDED_GROUP=$([[ "$MODE" == "nested" ]] && echo "outer_pve" || echo "direct_pve")
TARGETS=$(ansible-inventory -i inventory.yml --list 2>/dev/null | python3 -c '
import json, sys
grp = sys.argv[1]
try:
    inv = json.load(sys.stdin)
except Exception:
    sys.exit(0)
hosts = inv.get(grp, {}).get("hosts") or []
hv = inv.get("_meta", {}).get("hostvars", {})
for h in hosts:
    print("{} ({})".format(h, hv.get(h, {}).get("ansible_host", h)))
' "$NEEDED_GROUP" 2>/dev/null || true)
if [[ -z "$TARGETS" ]]; then
  rd "no hosts with ansible_host in group [$NEEDED_GROUP] — mode '$MODE' needs it in inventory.yml"
  exit 1
fi
gr "target group [$NEEDED_GROUP]:"
echo "$TARGETS" | sed 's/^/    /'

# warn-only ssh reachability (port 22) — inventory may carry ProxyJump etc.
while read -r line; do
  ip=$(echo "$line" | grep -oE '\([0-9.]+\)' | tr -d '()')
  [[ -z "$ip" ]] && continue
  if nc -z -w3 "$ip" 22 >/dev/null 2>&1; then
    gr "ssh reachable: $ip"
  else
    yl "ssh port 22 closed/unreachable: $ip (continuing — ansible will verify)"
  fi
done <<< "$TARGETS"

echo
cy "install plan"
echo "    mode        $MODE"
echo "    templates   $( [[ "$WITH_TEMPLATES" == "true" ]] && echo "build (multi-GB, multi-hour)" || echo "skip (--with-templates to build)" )"
echo "    dedicated   ${DEDICATED:-no}"
echo

SKIP_CONFIRM=""
[[ ! -t 0 ]] && SKIP_CONFIRM="non-interactive"
for a in "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"; do
  case "$a" in --check|--syntax-check|--list-tasks|--list-hosts|--list-tags) SKIP_CONFIRM="ansible $a" ;; esac
done
if [[ -z "$ASSUME_YES" && -z "$SKIP_CONFIRM" ]]; then
  printf "  proceed? [y/N] "
  read -r ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "aborted."; exit 1; }
fi

cy "installing ansible collections"
ansible-galaxy collection install -r requirements.yml
echo

EV=(install_mode="$MODE" install_templates="$WITH_TEMPLATES")
[[ -n "$DEDICATED" ]] && EV+=(i_know_dedicated=true)

mkdir -p logs
cy "running playbook — full log: installer/logs/install.log"
echo

trap 'rd "aborted — full log: installer/logs/install.log"; exit 130' INT

rc=0
# "${arr[@]+"${arr[@]}"}" — bash 3.2-safe expansion of a possibly-empty array
if [[ -n "$VERBOSE" ]]; then
  ANSIBLE_STDOUT_CALLBACK=default ansible-playbook site.yml -v \
    --extra-vars "$(printf '%s ' "${EV[@]}")" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || rc=$?
else
  ansible-playbook site.yml \
    --extra-vars "$(printf '%s ' "${EV[@]}")" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || rc=$?
fi
echo

if [[ $rc -ne 0 ]]; then
  rd "install failed (exit $rc)"
  yl "full log: installer/logs/install.log"
  last=$(grep '✗' logs/install.log 2>/dev/null | tail -1 || true)
  [[ -n "$last" ]] && echo "  last error: $last"
  yl "idempotent — re-run the same command to resume where it failed"
  exit "$rc"
fi

gr "install complete"
echo "    next: open http://<app-vm-ip>:8000 → setup wizard"
echo "          cli/pentrain doctor — environment sanity check"
