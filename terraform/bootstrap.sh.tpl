#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${app_root}"
REPO_URL="${repo_url}"
REPO_REF="${repo_ref}"

export DEBIAN_FRONTEND=noninteractive

sudo dnf update -y
sudo dnf install -y git python3.11 python3.11-pip python3.11-devel make gcc
sudo dnf install -y amazon-ssm-agent || true
sudo systemctl enable --now amazon-ssm-agent || true

if ! id bench >/dev/null 2>&1; then
  sudo useradd --create-home --shell /bin/bash bench
fi

sudo mkdir -p "$APP_ROOT"
sudo chown -R bench:bench "$APP_ROOT"

if [[ -n "$REPO_URL" ]]; then
  if [[ -d "$APP_ROOT/.git" ]]; then
    sudo -u bench git -C "$APP_ROOT" fetch --all --prune
    sudo -u bench git -C "$APP_ROOT" checkout "$REPO_REF"
    sudo -u bench git -C "$APP_ROOT" pull --ff-only origin "$REPO_REF"
  else
    sudo -u bench git clone --branch "$REPO_REF" "$REPO_URL" "$APP_ROOT"
  fi
fi

sudo mkdir -p "$APP_ROOT/configs"
sudo tee "$APP_ROOT/configs/.env" >/dev/null <<'EOF'
PG_HOST=${pg_host}
PG_PORT=${pg_port}
PG_DBNAME=${pg_dbname}
PG_USER=${pg_user}
PG_PASSWORD=${pg_password}
PG_APP_ETL=${pg_app_etl}
PG_APP_ELT=${pg_app_elt}

PG_SUPER_USER=${pg_super_user}
PG_SUPER_PASS=${pg_super_pass}
EOF
sudo chmod 600 "$APP_ROOT/configs/.env"
sudo chown -R bench:bench "$APP_ROOT/configs/.env"

if [[ -f "$APP_ROOT/pyproject.toml" ]]; then
  sudo -u bench python3.11 -m venv "$APP_ROOT/.venv"
  sudo -u bench "$APP_ROOT/.venv/bin/pip" install --upgrade pip
  sudo -u bench "$APP_ROOT/.venv/bin/pip" install -e "$APP_ROOT"
  sudo -u bench env PROJECT_ROOT="$APP_ROOT" "$APP_ROOT/.venv/bin/python" -m bench_monitoring.init_db
fi

sudo tee /etc/profile.d/bench-monitoring.sh >/dev/null <<EOF
export BENCH_APP_ROOT="$APP_ROOT"
EOF
