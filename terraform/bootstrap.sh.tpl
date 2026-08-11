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
PG_SSLMODE=require
PG_APP_ETL=${pg_app_etl}
PG_APP_ELT=${pg_app_elt}

PG_SUPER_USER=${pg_super_user}
PG_SUPER_PASS=${pg_super_pass}
EOF
sudo chmod 600 "$APP_ROOT/configs/.env"
sudo chown -R bench:bench "$APP_ROOT/configs/.env"

sudo tee "$APP_ROOT/configs/infrastructure.json" >/dev/null <<EOF
{
  "project_name": "${bench_project_name}",
  "environment": "${bench_environment}",
  "ec2_instance_type": "${bench_ec2_type}",
  "db_instance_class": "${bench_db_instance}",
  "s3_results_bucket": "${bench_s3_bucket}",
  "s3_results_key_prefix": "${bench_s3_key_prefix}",
  "app_root": "${app_root}"
}
EOF
sudo chmod 600 "$APP_ROOT/configs/infrastructure.json"
sudo chown bench:bench "$APP_ROOT/configs/infrastructure.json"

sudo tee /etc/profile.d/bench-monitoring.sh >/dev/null <<EOF
export BENCH_APP_ROOT="$APP_ROOT"
export BENCH_INFRA_METADATA="$APP_ROOT/configs/infrastructure.json"
export BENCH_PROJECT_NAME="${bench_project_name}"
export BENCH_ENVIRONMENT="${bench_environment}"
export BENCH_EC2_INSTANCE_TYPE="${bench_ec2_type}"
export BENCH_DB_INSTANCE_CLASS="${bench_db_instance}"
export BENCH_RESULTS_BUCKET="${bench_s3_bucket}"
export BENCH_RESULTS_KEY_PREFIX="${bench_s3_key_prefix}"
EOF

if [[ -f "$APP_ROOT/pyproject.toml" ]]; then
  sudo -u bench python3.11 -m venv "$APP_ROOT/.venv"
  sudo -u bench "$APP_ROOT/.venv/bin/pip" install --upgrade pip
  sudo -u bench "$APP_ROOT/.venv/bin/pip" install -e "$APP_ROOT"
  sudo -u bench env PROJECT_ROOT="$APP_ROOT" "$APP_ROOT/.venv/bin/python" -m bench_monitoring.init_db
fi

