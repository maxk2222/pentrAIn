#!/usr/bin/env bash
# pentrAIn installer — wraps ansible-playbook with mode + safety flags.
set -euo pipefail

cd "$(dirname "$0")"

MODE=""
DEDICATED=""
WITH_TEMPLATES="false"
EXTRA_ARGS=()

usage() {
  cat <<EOF
pentrAIn installer

  --mode nested|direct    required
                          nested = create engine VM on existing Proxmox (default home-server path)
                          direct = use an existing *dedicated* Proxmox host
  --i-know-dedicated      direct mode only, required when the host already has VMs
  --with-templates        also build the large Ludus templates (kali, debian) — multi-GB
  -h, --help              this help

Examples:
  ./install.sh --mode nested
  ./install.sh --mode direct --i-know-dedicated --with-templates
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --i-know-dedicated) DEDICATED="true"; shift ;;
    --with-templates) WITH_TEMPLATES="true"; shift ;;
    -h|--help) usage ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

[[ -z "$MODE" ]] && { echo "ERROR: --mode required"; usage; }
[[ "$MODE" != "nested" && "$MODE" != "direct" ]] && { echo "ERROR: mode must be nested|direct"; usage; }

# direct mode requires explicit acknowledgement when the host has workloads —
# the preflight role enforces it; we pass the flag through.
EV=(install_mode="$MODE" install_templates="$WITH_TEMPLATES")
[[ -n "$DEDICATED" ]] && EV+=(i_know_dedicated=true)

# ensure an ssh key exists for VM cloud-init injection
if [[ ! -f /root/.ssh/id_rsa.pub && ! -f "$HOME/.ssh/id_rsa.pub" ]]; then
  echo "[*] generating ssh key for VM access"
  ssh-keygen -t rsa -b 4096 -N "" -f "$HOME/.ssh/id_rsa" || true
fi

command -v ansible-playbook >/dev/null || {
  echo "ERROR: ansible not installed. apt install ansible, or pipx install ansible-core"; exit 1;
}

echo "[*] installing ansible collections"
ansible-galaxy collection install -r requirements.yml

[[ -f inventory.yml ]] || {
  echo "ERROR: inventory.yml missing — cp inventory.example.yml inventory.yml and fill in your host"; exit 1;
}

echo "[*] pentrAIn install — mode=$MODE templates=$WITH_TEMPLATES dedicated=${DEDICATED:-no}"

exec ansible-playbook site.yml \
  --extra-vars "$(printf '%s ' "${EV[@]}")" \
  "${EXTRA_ARGS[@]}"
