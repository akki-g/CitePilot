#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "bootstrap: run with sudo" >&2
  exit 2
fi

app_user="${APP_USER:-ubuntu}"
app_dir="${APP_DIR:-/opt/citepilot}"
repo_url="${REPO_URL:-https://github.com/akki-g/CitePilot.git}"

if ! id "$app_user" >/dev/null 2>&1; then
  echo "bootstrap: Linux user '$app_user' does not exist" >&2
  exit 2
fi

apt-get update
apt-get install -y ca-certificates curl git gnupg jq

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  architecture="$(dpkg --print-architecture)"
  echo "deb [arch=$architecture signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker
usermod -aG docker "$app_user"

install -d -o "$app_user" -g "$app_user" "$app_dir"
if [[ ! -d "$app_dir/.git" ]]; then
  if [[ -n "$(find "$app_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "bootstrap: $app_dir is not empty" >&2
    exit 3
  fi
  sudo -u "$app_user" git clone "$repo_url" "$app_dir"
fi

if [[ ! -f "$app_dir/.env.production" ]]; then
  install -o "$app_user" -g "$app_user" -m 0600 \
    "$app_dir/.env.production.example" "$app_dir/.env.production"
fi
install -d -o "$app_user" -g "$app_user" -m 0700 "$app_dir/backups"

if systemctl list-unit-files | grep -q '^amazon-ssm-agent'; then
  systemctl enable --now amazon-ssm-agent
elif systemctl list-unit-files | grep -q '^snap.amazon-ssm-agent.amazon-ssm-agent'; then
  systemctl enable --now snap.amazon-ssm-agent.amazon-ssm-agent
else
  echo "bootstrap: warning: SSM Agent was not found; install it before enabling CI/CD" >&2
fi

echo
echo "Bootstrap complete. Next:"
echo "  1. Edit $app_dir/.env.production and replace every placeholder."
echo "  2. Attach an EC2 role with AmazonSSMManagedInstanceCore."
echo "  3. Install one reverse-proxy template for your CitePilot hostname."
echo "  4. Log out/in once so $app_user receives Docker group membership."
