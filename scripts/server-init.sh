#!/usr/bin/env bash
# WebChat AI - initialize a fresh Ubuntu/Debian server for production.
#
# Idempotent: safe to re-run at any time (e.g. on first boot / after a restore).
# See docs/ORACLE_FREE_VM_DEPLOYMENT.md.
#
# Example:
#   sudo -i
#   APP_DIR=/opt/webchat-ai \
#   REPO_URL=https://github.com/your-org/webchat-AI.git \
#   bash scripts/server-init.sh
#
# Optional env:
#   APP_DIR     deployment directory      (default: /opt/webchat-ai)
#   REPO_URL    clone from this URL when $APP_DIR is not a git repo
#   ENABLE_UFW  configure firewall (1/0)   (default: 1)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/webchat-ai}"
REPO_URL="${REPO_URL:-}"
ENABLE_UFW="${ENABLE_UFW:-1}"

log()  { printf '\n==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- must be root -----------------------------------------------------------
[[ "$(id -u)" -eq 0 ]] || die "run as root: sudo -i"

# --- OS support -------------------------------------------------------------
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *) die "unsupported distro '${ID:-unknown}' - Ubuntu or Debian required" ;;
esac

# --- required packages ------------------------------------------------------
log "Installing base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg git jq ufw

# --- Docker Engine ----------------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  log "Docker already installed and running"
else
  log "Installing Docker Engine (official apt repository)"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io
  systemctl enable --now docker
  docker info >/dev/null 2>&1 || die "Docker daemon did not start"
fi

# --- Docker Compose plugin --------------------------------------------------
if docker compose version >/dev/null 2>&1; then
  log "Docker Compose plugin already installed: $(docker compose version --short)"
else
  log "Installing Docker Compose plugin"
  apt-get install -y docker-compose-plugin
  docker compose version >/dev/null 2>&1 || die "compose plugin install failed (docker compose version)"
fi

# --- Firewall (UFW) ---------------------------------------------------------
if [[ "${ENABLE_UFW}" == "1" ]]; then
  log "Configuring UFW (allow 22/tcp 80/tcp 443/tcp)"
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  ufw status verbose
else
  log "Skipping UFW configuration (ENABLE_UFW=0)"
fi

# --- Directory layout -------------------------------------------------------
log "Creating deployment directories under ${APP_DIR}"
mkdir -p "${APP_DIR}/tls"          # optional nginx certs (fullchain.pem + privkey.pem)
mkdir -p "${APP_DIR}/data/redis"   # optional self-hosted Redis (see compose override)

# --- Clone the repository ---------------------------------------------------
if [[ -n "${REPO_URL}" ]]; then
  if [[ -d "${APP_DIR}/.git" ]]; then
    log "Repository already present - pulling latest"
    git -C "${APP_DIR}" fetch origin && git -C "${APP_DIR}" pull --ff-only
  else
    log "Cloning ${REPO_URL} -> ${APP_DIR}"
    git clone "${REPO_URL}" "${APP_DIR}"
  fi
elif [[ ! -d "${APP_DIR}/.git" ]]; then
  log "REPO_URL not set and ${APP_DIR} is not a git repo"
  log "Clone manually:  git clone <repo> ${APP_DIR}"
fi

# --- Environment template ---------------------------------------------------
ENV_FILE="${APP_DIR}/.env.production"
if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${APP_DIR}/.env.production.example" ]]; then
    cp "${APP_DIR}/.env.production.example" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    log "Created ${ENV_FILE} from template - EDIT IT NOW and fill in real secrets"
    printf '  e.g.  openssl rand -hex 32   # -> JWT_SECRET\n'
    printf '        nano %s\n' "${ENV_FILE}"
  else
    log "No .env.production.example found - create ${ENV_FILE} from docs/ORACLE_FREE_VM_DEPLOYMENT.md"
  fi
else
  log "${ENV_FILE} already exists (kept as-is)"
fi

log "Server init complete."
log "Next: edit ${ENV_FILE}, then run:  ${APP_DIR}/scripts/deploy-production.sh"
